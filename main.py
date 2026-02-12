from flask import Flask, render_template,redirect,abort,request,url_for,flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import check_password_hash


import pymysql

from dynaconf import Dynaconf

app = Flask(__name__)


config = Dynaconf(settings_file = [ "settings.toml" ])

def connect_db():
    conn = pymysql.connect(
        host= "db.steamcenter.tech",
        user= config.username,
        password= config.password,
        database="back_stage",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor
    )  

    return conn

@app.route("/")
def index():
   return render_template("index.html.jinja")

@app.route("/login")
def login():
    return render_template("login.html.jinja")



@app.route("/register", methods=["POST", "GET"])
def register():  
        if request.method == "POST":
            name = request.form["name"]

            email = request.form["email"]

            password = request.form["password"]
            confirm_password = request.form["confirm_password"]

            if password != confirm_password:
                flash("Passwords do not match!")
            elif len(password) < 8:
                flash("Password must be at least 8 characters long!")
                flash("password is too short")
                
            else:
                connection = connect_db()

                cursor = connection.cursor()
                
                try:
                    cursor.execute(
                        'INSERT INTO `User` (`Name`, `email`, `password`, ) VALUES (%s, %s, %s, %s)',
                        (name, email, password, ))
                except pymysql.err.IntegrityError:
                    flash("Email already registered!")
                    connection.close()
                else:
                    connection.commit()  
                    connection.close()
                    return redirect('/login')
        
        return render_template("register.html.jinja")