import os
import datetime
import bcrypt
import pymongo
from flask import Flask, app, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin,login_user, logout_user, login_required, current_user
from bson.objectid import ObjectId
from pymongo import MongoClient, ASCENDING
from dotenv import load_dotenv, dotenv_values
from datetime import datetime, timezone

load_dotenv()
def create_app():
    #load flask config from env variables
    app = Flask(__name__)
    config = dotenv_values()
    app.config.from_mapping(config)

    #Mongo connection
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

    #flask_login setup
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


    # Signup/Login/Logout
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
    



app = create_app()

if __name__ == "__main__":
    FLASK_PORT = os.getenv("FLASK_PORT", "5000")
    FLASK_ENV = os.getenv("FLASK_ENV")
    print(f"FLASK_ENV: {FLASK_ENV}, FLASK_PORT: {FLASK_PORT}")
    app.run(port=FLASK_PORT)