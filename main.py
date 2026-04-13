from flask import Flask, render_template, redirect, abort, request, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
import os
import pymysql
from dynaconf import Dynaconf

# --- Configuration ---
UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

config = Dynaconf(settings_file=["settings.toml"])
app.secret_key = config.secret_key

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Login Manager ---
login_mannager = LoginManager(app)
login_mannager.login_view = '/login'

class User(UserMixin):
    def __init__(self, result):
        self.name = result['name']
        self.email = result['email']
        self.id = result['User_ID']

@login_mannager.user_loader
def local_user(user_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM `User` WHERE `User_ID` = %s", (user_id,))
    result = cursor.fetchone()
    connection.close()
    return User(result) if result else None

def connect_db():
    return pymysql.connect(
        host="db.steamcenter.tech",
        user=config.username,
        password=config.password,
        database="back_stage",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor
    )

# --- Routes ---

@app.route("/")
def index():
    return render_template("index.html.jinja")

@app.route("/login", methods=['POST', 'GET'])
def login():
    if request.method == "POST":
        username = request.form['name']
        password = request.form['password']

        connection = connect_db()
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM `User` WHERE `name` = %s", (username,))
        result = cursor.fetchone()
        connection.close()

        if result is None:
            flash("No user found")
        # NOTE: In production, use check_password_hash! 
        # Using simple equality for now based on your code.
        elif password != result["password"]:
            flash("Incorrect password")
        else:
            login_user(User(result))
            return redirect(url_for('matching'))
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
            flash("Password too short!")
        else:
            connection = connect_db()
            cursor = connection.cursor()
            try:
                # 1. Create User
                cursor.execute(
                    'INSERT INTO `User` (`name`, `email`, `password`) VALUES (%s, %s, %s)',
                    (name, email, password)
                )
                user_id = cursor.lastrowid
                
                # 2. Create blank Profile immediately to prevent UndefinedError later
                cursor.execute(
                    'INSERT INTO `Profile` (`Profile_name`, `discography`, `description`, `Matches_ID`, `Profile_picture`, `User_ID`) VALUES (%s, %s, %s, %s, %s, %s)',
                    (name, "No discography yet", "No description yet", 0, "default", user_id)
                )
                return redirect(url_for('login'))
            except pymysql.err.IntegrityError:
                flash("Email or Username already taken!")
            finally:
                connection.close()
    return render_template("register.html.jinja")

@app.route("/profile")
@login_required
def profile():
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute('SELECT * FROM `Profile` WHERE `User_ID` = %s', (current_user.id,))
    result = cursor.fetchone()
    connection.close()

    # FIX: If profile is missing, don't crash. Send them to settings.
    if not result:
        flash("Please set up your profile first!")
        return redirect(url_for('profile_settings'))
        
    return render_template("profile.html.jinja", Profile=result)

@app.route('/profile_customization', methods=["GET", "POST"])
@login_required
def profile_settings():
    connection = connect_db()
    cursor = connection.cursor()

    if request.method == 'POST':
        profile_name = request.form["Profile_name"]
        discography = request.form["discography"]
        description = request.form["description"]
        file = request.files.get("Profile_picture")

        filename = "default"
        if file and allowed_file(file.filename):
            filename = secure_filename(f"user_{current_user.id}_{file.filename}")
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        cursor.execute("""
            UPDATE `Profile`
            SET `Profile_name` = %s, `Profile_picture` = %s, `discography` = %s, `description` = %s
            WHERE `User_ID` = %s
        """, (profile_name, filename, discography, description, current_user.id))
        return redirect(url_for('profile'))

    cursor.execute('SELECT * FROM `Interest`')
    interests = cursor.fetchall()
    connection.close()
    return render_template("profile_customization.html.jinja", Interest=interests)

@app.route('/interest', methods=["POST"])
@login_required
def interest_form():
    interests = request.form.getlist("interest")
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM `User_Interest` WHERE `User_ID` = %s", (current_user.id,))
    for i_id in interests:
        cursor.execute("INSERT INTO `User_Interest` (`Interest_ID`, `User_ID`) VALUES (%s, %s)", (i_id, current_user.id))
    connection.close()
    return redirect(url_for('profile'))

@app.route("/matching")
@login_required
def matching():
    connection = connect_db()
    cursor = connection.cursor()
    
    # Get current user's interests
    cursor.execute("SELECT * FROM User_Interest WHERE User_ID = %s", (current_user.id,))
    my_interest_ids = [int(row.get('Interest_ID') or row.get('interest_ID')) for row in cursor.fetchall()]

    # Get potential matches
    cursor.execute("""
        SELECT u.User_ID, u.name, p.Profile_name, p.description, p.discography, p.Profile_picture, ui.interest_ID
        FROM User u
        JOIN Profile p ON u.User_ID = p.User_ID
        LEFT JOIN User_Interest ui ON u.User_ID = ui.User_ID
        WHERE u.User_ID != %s
    """, (current_user.id,))
    all_rows = cursor.fetchall()
    connection.close()

    # Filter by interest
    profiles_in_feed = []
    seen = set()
    for row in all_rows:
        i_id = row.get('interest_ID') or row.get('Interest_ID')
        if i_id and int(i_id) in my_interest_ids and row['User_ID'] not in seen:
            profiles_in_feed.append(row)
            seen.add(row['User_ID'])

    index = request.args.get('index', 0, type=int)
    display = profiles_in_feed[index] if index < len(profiles_in_feed) else None

    return render_template("matching.html.jinja", profile=display, next_index=index + 1)

@app.route('/invites')
@login_required
def view_invites():
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("""
        SELECT u.User_ID, u.email, p.Profile_name, p.Profile_picture
        FROM User u
        JOIN Profile p ON u.User_ID = p.User_ID
        JOIN invites i ON u.User_ID = i.User_1
        WHERE i.User_2 = %s
    """, (current_user.id,))
    received = cursor.fetchall()
    connection.close()
    return render_template("invites.html.jinja", Invites_sent_to_user=received)

@app.route('/invites/<target_id>/send', methods=["POST"])
@login_required
def invites_send(target_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("INSERT INTO `invites` (`User_1`, `User_2`) VALUES (%s, %s)", (current_user.id, target_id))
    connection.close()
    return redirect(url_for('matching', index=request.args.get('index', 0)))

@app.route('/invites/<sender_id>/accept', methods=["POST"])
@login_required
def accept_invite(sender_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("INSERT INTO `Matches` (`User_1`, `User_2`) VALUES (%s, %s)", (sender_id, current_user.id))
    cursor.execute("DELETE FROM `invites` WHERE `User_1` = %s AND `User_2` = %s", (sender_id, current_user.id))
    connection.close()
    return redirect(url_for('view_invites'))

@app.route('/invites/<sender_id>/decline', methods=["POST"])
@login_required
def decline_invite(sender_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM `invites` WHERE `User_1` = %s AND `User_2` = %s", (sender_id, current_user.id))
    connection.close()
    return redirect(url_for('view_invites'))

@app.route('/collaborate')
@login_required
def collaborations():
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("""
        SELECT u.User_ID, u.name, u.email, p.Profile_name, p.Profile_picture
        FROM Matches m
        JOIN User u ON (m.User_1 = u.User_ID OR m.User_2 = u.User_ID)
        JOIN Profile p ON u.User_ID = p.User_ID
        WHERE (m.User_1 = %s OR m.User_2 = %s) AND u.User_ID != %s
    """, (current_user.id, current_user.id, current_user.id))
    collabs = cursor.fetchall()
    connection.close()
    return render_template("collaborate.html.jinja", Collabrations=collabs)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/")