import os
import datetime
import bcrypt
import pymongo
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from bson.objectid import ObjectId
from pymongo import MongoClient, ASCENDING
from dotenv import load_dotenv, dotenv_values

load_dotenv()

def create_app():
    # config setup and db connection
    app = Flask(__name__)
    config = dotenv_values()
    app.config.from_mapping(config)
    app.secret_key = app.config.get("SECRET_KEY")

    cxn = pymongo.MongoClient(os.getenv("MONGO_URI"))
    db = cxn[os.getenv("MONGO_DBNAME")]
    try:
        cxn.admin.command("ping")
        print(" *", "Connected to MongoDB!")
    except Exception as e:
        print(" * MongoDB connection error:", e)

    users = db.users
    games = db.games
    messages = db.messages

    # flask login setup
    login_manager = LoginManager()
    login_manager.init_app(app)

    class User(UserMixin):
        def __init__(self, doc):
            self.doc = doc
        def get_id(self):
            return str(self.doc["_id"])

    @login_manager.user_loader
    def load_user(user_id):
        doc = users.find_one({"_id": ObjectId(user_id)})
        return User(doc) if doc else None

    # game logic helpers
    def parse_dt(s):
        try:
            return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M")
        except Exception:
            return None

    def validate_game(f):
        sport = f.get("sport").lower()
        gym = f.get("gym")
        start_dt = parse_dt(f.get("start_time"))
        end_dt = parse_dt(f.get("end_time"))
        notes = (f.get("notes") or "").strip()

        try:
            needed_players = int(f.get("needed_players") or 0)
        except ValueError:
            return None, "Needed players must be a number."

        if not start_dt or not end_dt:
            return None, "Start and end times are required."

        now = datetime.datetime.now()
        if start_dt < now or end_dt < now:
            return None, "Games must be scheduled in the future."

        if not (start_dt < end_dt):
            return None, "Start time must be before end time."

        # facility hours: 9 AM to 7 PM
        if not (9 <= start_dt.hour < 19 and 9 < end_dt.hour <= 19):
            return None, "Games must be between 9 AM and 7 PM."

        # duration limit: 60 minutes
        duration = (end_dt - start_dt).total_seconds()
        if duration <= 0 or duration > 3600:
            return None, "Game duration must be > 0 and ≤ 60 minutes."

        # Needed players: 1 through 10; also set max_players = needed_players
        if not (1 <= needed_players <= 10):
            return None, "Needed players must be between 1 and 10."

        return {
            "sport": sport,
            "gym": gym,
            "start_time": start_dt,
            "end_time": end_dt,
            "needed_players": needed_players,
            "max_players": needed_players,
            "notes": notes,
        }, None

    # ----- Signup/Login/Logout -----
    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "POST":
            email = request.form["email"].lower().strip()
            password = request.form["password"]

            if not email.endswith("@nyu.edu"):
                flash("You must use an @nyu.edu email.")
                return redirect(url_for("signup"))

            if users.find_one({"email": email}):
                flash("Email already registered.")
                return redirect(url_for("signup"))

            hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
            users.insert_one({
                "email": email,
                "password": hashed.decode("utf-8"),
                "created_at": datetime.datetime.utcnow()
            })

            flash("Account created successfully. Please log in.")
            return redirect(url_for("login"))
        return render_template("signup.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form["email"].lower().strip()
            password = request.form["password"]

            user_doc = users.find_one({"email": email})
            if not user_doc:
                flash("Invalid email or password.")
                return redirect(url_for("login"))

            if not bcrypt.checkpw(password.encode("utf-8"), user_doc["password"].encode("utf-8")):
                flash("Invalid email or password.")
                return redirect(url_for("login"))

            user = User(user_doc)
            login_user(user)
            flash("Logged in successfully!")
            return redirect(url_for("home"))
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        flash("You’ve logged out.")
        return redirect(url_for("home"))


    # GAME ROUTES

    # Home: upcoming games -- home.html
    @app.get("/")
    def home():
        now = datetime.datetime.now()
        docs = games.find({"start_time": {"$gte": now}}).sort("start_time", 1)
        return render_template("home.html", games=list(docs))

    # Create: form (GET) -- create_game.html
    @app.get("/games/create")
    @login_required
    def create_game_form():
        now_min = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
        return render_template("create_game.html", NOW_MIN=now_min)

    # Create: submit (POST) -- create_game.html
    @app.post("/games/create")
    @login_required
    def create_game_post():
        data, error = validate_game(request.form)
        if error:
            flash(error)
            return redirect(url_for("create_game_form"))

        new_game = {
            **data,
            "player_ids": [str(current_user.get_id())],
            "created_by": str(current_user.get_id()),
            "created_at": datetime.datetime.now(datetime.timezone.utc),
            "updated_at": datetime.datetime.now(datetime.timezone.utc),
        }
        result = games.insert_one(new_game)
        flash("Game created successfully.")
        return redirect(url_for("game_detail", game_id=str(result.inserted_id)))
    # Game details: (GET) -- game_detail.html
    @app.get("/games/<game_id>")
    def game_detail(game_id):
       game = games.find_one({"_id": ObjectId(game_id)})
       if not game:
           flash("Game not found.")
           return redirect(url_for("home"))
       user_id = str(current_user.get_id()) if current_user.is_authenticated else None
       return render_template("game_detail.html", game=game, user_id=user_id)
    
    # Games list: filter search -- games.html
    @app.get("/games")
    def games_list():
       now = datetime.datetime.now()
       query = {"start_time": {"$gte": now}}


       sport = request.args.get("sport")
       gym = request.args.get("gym")
       date_from = request.args.get("date_from")
       date_to = request.args.get("date_to")


       if sport:
           query["sport"] = sport.lower()
       if gym:
           query["gym"] = gym
       if date_from:
           query["start_time"]["$gte"] = datetime.datetime.strptime(date_from, "%Y-%m-%d")
       if date_to:
           query["start_time"]["$lt"] = datetime.datetime.strptime(date_to, "%Y-%m-%d") + datetime.timedelta(days=1)


       games_list_cursor = games.find(query).sort("start_time", 1)
       return render_template("games.html", games=list(games_list_cursor))


    return app


# can consider this /main
app = create_app()
print("create_app() returned:", type(app))

if __name__ == "__main__":
    FLASK_PORT = os.getenv("FLASK_PORT", "5000")
    FLASK_ENV = os.getenv("FLASK_ENV")
    print(f"FLASK_ENV: {FLASK_ENV}, FLASK_PORT: {FLASK_PORT}")
    app.run(port=FLASK_PORT)