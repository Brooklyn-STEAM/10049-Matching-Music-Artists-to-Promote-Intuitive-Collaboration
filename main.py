from flask import Flask, render_template,redirect,abort,request,url_for,flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import check_password_hash


import pymysql

from dynaconf import Dynaconf

app = Flask(__name__)
config = Dynaconf(settings_file = ["settings.toml"])

app.secret_key = config.secret_key

login_mannager = LoginManager( app )

login_mannager.login_view = '/login'

class User:
    is_authenticated =True
    is_active = True
    is_anonymous = False

    def __init__ (self, result):
        self.name = result ['Name']
        self.email = result ['Email']
        self.birthday = result['BirthDate']
        self.id = result ['ID']

    def get_id(self):
        return str(self.id)

@login_mannager.user_loader
def local_user(user_id):
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute(" SELECT  * FROM `User` WHERE `ID` = %s", (user_id) )

    result = cursor.fetchone()

    connection.close

    if result is None:
        return None
    
    return User(result)

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
    if request.method == 'POST':

        email = request.form ['username']

        password = request.form ['password']

        connection = connect_db()

        cursor = connection.cursor()

        cursor.execute(" SELECT * FROM `User` WHERE `Email` = %s ", ( email ))

        result = cursor.fetchone()

        connection.close()
        
        if result is None:
            flash("No user found")
        elif password is result["Password"]:
            flash("Incorrect password")
        else:
            login_user(User(result))
            return redirect('/browse')
        
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




@app.route("/profile/customization")
def customize():
    connection = connect_db()

    cursor = connection.cursor()

    connection.close()


    return render_template("profile.html.jinja")