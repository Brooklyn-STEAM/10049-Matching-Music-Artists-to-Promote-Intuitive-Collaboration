from flask import Flask, render_template,redirect,abort,request,url_for,flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename


UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}


import os
import pymysql

from dynaconf import Dynaconf

app = Flask(__name__)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

config = Dynaconf(settings_file = ["settings.toml"])

app.secret_key = config.secret_key

login_mannager = LoginManager( app )

login_mannager.login_view = '/login'

class User:
    is_authenticated =True
    is_active = True
    is_anonymous = False

    def __init__ (self, result):
        self.name = result ['name']
        self.email = result ['email']
        self.id = result ['User_ID']

    def get_id(self):
        return str(self.id)

@login_mannager.user_loader
def local_user(user_id):
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute(" SELECT  * FROM `User` WHERE `User_ID` = %s", (user_id) )

    result = cursor.fetchone()

    connection.close()

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

@app.route("/login", methods = ['POST','GET'])
def login():
    if request.method == "POST":

        username = request.form ['name']

        password = request.form ['password']

        connection = connect_db()

        cursor = connection.cursor()

        cursor.execute(" SELECT * FROM `User` WHERE `name` = %s ", ( username ))

        result = cursor.fetchone()

        connection.close()
        
        if result is None:
            flash("No user found")
        elif password is result["password"]:
            flash("Incorrect password")
        else:
            login_user(User(result))
            return redirect('/matching')
        
    return render_template("login.html.jinja")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/")
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
                        'INSERT INTO `User` (`Name`, `email`, `password` ) VALUES (%s, %s, %s)',
                        (name, email, password,) )
                    User_ID = cursor.lastrowid
                    cursor.execute(
                    'INSERT INTO `Profile` (`Profile_name`, `discography`, `description`,`Matches_ID`,`Profile_picture`,`User_ID` ) VALUES ("default","default","defualt",0,"default",%s)', (User_ID))
                except pymysql.err.IntegrityError:
                    flash("Email already registered!")
                    connection.close()
                else:
                    connection.commit()  
                    connection.close()
                    return redirect('/login')
        
        return render_template("register.html.jinja")



@app.route("/profile")
@login_required
def profile():
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute('SELECT * FROM `Profile` WHERE `User_ID` = %s',(current_user.id,))
    result = cursor.fetchone()
    connection.close()

    if result is None:
        flash("Profile not found.")
    return render_template("profile.html.jinja", Profile = result )

    # create a form to create a profile 
    # profile contain discography and a decription and the individuals selceted interests
@app.route('/profile_customization', methods=["GET","POST"])
@login_required
def profile_settings():
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute('SELECT * FROM `Interest`')

    result = cursor.fetchall()

    connection.close()

    if request.method == 'POST':

        Profile_name = request.form["Profile_name"]

        discography = request.form["discography"]

        description = request.form["description"]

        file = request.files["Profile_picture"]

        filename = None

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)

            filename = f"user_{current_user.id}_{filename}"

            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        connection = connect_db()

        cursor = connection.cursor()

        cursor.execute("""
        UPDATE `Profile`
        SET `Profile_name` = %s,
        `Profile_picture` = %s,
        `discography` = %s,
        `description` = %s
        WHERE `User_ID` = %s
        """, (Profile_name, filename, discography, description, current_user.id))
        connection.commit()
        connection.close()
        
    return render_template("profile_customization.html.jinja", Interest = result)

@app.route('/interest', methods=["GET", "POST"])
@login_required
def interest_form():
    if request.method == 'POST':

        interests = request.form.getlist("interest")  # gets all checked boxes

        connection = connect_db()
        cursor = connection.cursor()

        # Optional: remove old interests first so they don't duplicate
        cursor.execute("""
            DELETE FROM `User_Interest`
            WHERE `User_ID` = %s
        """, (current_user.id,))

        # Insert each selected interest
        for interest_id in interests:
            cursor.execute("""
                INSERT INTO `User_Interest` (`Interest_ID`, `User_ID`)
                VALUES (%s, %s)
            """, (interest_id, current_user.id))

        connection.commit()
        connection.close()

    return redirect("/profile")



@app.route("/matching")
@login_required
def matching():
    connection = connect_db()
    cursor = connection.cursor()
    
    # 1. Fetch all potential matches (Everyone except the current user)
    # Joining tables so we have Profile and User data ready for the frontend
    cursor.execute("""
        SELECT 
            User.User_ID, 
            User.name, 
            Profile.Profile_name, 
            Profile.description, 
            Profile.discography, 
            Profile.Profile_picture,
            User_Interest.interest_ID
        FROM User_Interest
        JOIN Profile ON User_Interest.User_ID = Profile.User_ID
        JOIN User ON Profile.User_ID = User.User_ID
        WHERE User.User_ID != %s
    """, (current_user.id,))
    all_potential_rows = cursor.fetchall()
    
    # 2. Fetch the current user's interests
    cursor.execute("SELECT interest_ID FROM User_Interest WHERE User_ID = %s", (current_user.id,))
    raw_my_interests = cursor.fetchall()
    connection.close()

    # FIX 1: Use lowercase 'interest_ID' to match your SELECT above
    my_interest_ids = [int(row['interest_ID']) for row in raw_my_interests]

    profiles_in_feed = []
    seen_user_ids = set()

    for row in all_potential_rows:
        # FIX 2: Again, use the key that matches your big SELECT statement
        # Using .get() is safer as it returns None instead of crashing
        val = row.get('interest_ID')
        
        if val is not None:
            current_row_interest = int(val)
            if current_row_interest in my_interest_ids:
                if row['User_ID'] not in seen_user_ids:
                    profiles_in_feed.append(row)
                    seen_user_ids.add(row['User_ID'])

    # 4. Pagination Logic
    # Get the 'index' from the URL (e.g., /matching?index=1). Default to 0.
    current_index = request.args.get('index', default=0, type=int)
    
  
    # Select only the specific profile for this index
    display_profile = None
    if 0 <= current_index < len(profiles_in_feed):
        display_profile = profiles_in_feed[current_index]

    return render_template(
        "matching.html.jinja", 
        profile=display_profile, 
        next_index=current_index + 1,
        total_matches=len(profiles_in_feed)
    )


@app.route('/collaborate')
@login_required
def collaborate():
    print("hello")
    return render_template("collaborate.html.jinja")