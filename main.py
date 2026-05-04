from flask import Flask, render_template, redirect, abort, request, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
import os
import pymysql
from dynaconf import Dynaconf

# --- Configuration ---
UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "mp3", "mp4", "wav", "ogg","webp"}

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
                    'INSERT INTO `Profile` (`Profile_name`,`description`, `Matches_ID`, `Profile_picture`, `User_ID`) VALUES (%s, %s, %s, %s, %s)',
                    (name, "No description yet", 0, "default", user_id)
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
    
    # 1. Fetch Profile Info
    cursor.execute('SELECT * FROM `Profile` WHERE `User_ID` = %s', (current_user.id,))
    profile_data = cursor.fetchone()

    #2. Fetch Interest of user
    cursor.execute("""
        SELECT Interest.name, Interest.interest_ID
        FROM User_Interest
        JOIN Interest ON User_Interest.interest_ID = Interest.interest_ID
        WHERE User_Interest.User_ID = %s
    """, (current_user.id,))
    user_interests = cursor.fetchall()

    #4. Fetch Songs from the NEW table
    cursor.execute('SELECT * FROM `Discography` WHERE `ID` = %s', (current_user.id,))
    songs = cursor.fetchall()
    
    connection.close()

    if not profile_data:
        return redirect(url_for('profile_settings'))
        
    return render_template("profile.html.jinja", Profile=profile_data, Songs=songs, user_interests=user_interests )

@app.route('/profile_customization', methods=["GET", "POST"])
@login_required
def profile_settings():
    connection = connect_db()
    cursor = connection.cursor()

    if request.method == 'POST':
        profile_name = request.form["Profile_name"]
        description = request.form["description"]
        file = request.files.get("Profile_picture")

        filename = "default"
        if file and allowed_file(file.filename):
            filename = secure_filename(f"user_{current_user.id}_{file.filename}")
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        cursor.execute("""
            UPDATE `Profile`
            SET `Profile_name` = %s, `Profile_picture` = %s, `description` = %s
            WHERE `User_ID` = %s
        """, (profile_name, filename, description, current_user.id))
        
        flash("Profile picture/description has been updated successfully!") 
        connection.close()
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
    flash("Your interests have been updated successfully!")
    return redirect(url_for('profile'))

@app.route("/matching")
@login_required
def matching():
    connection = connect_db()
    cursor = connection.cursor()
    
    # 1. Get current user's interests
    cursor.execute("SELECT * FROM User_Interest WHERE User_ID = %s", (current_user.id,))
    my_interest_ids = [int(row.get('Interest_ID') or row.get('interest_ID')) for row in cursor.fetchall()]

    # 2. Get potential matches (Note: I removed p.discography since you deleted that column)
    cursor.execute("""
        SELECT u.User_ID, u.name, p.Profile_name, p.description, p.Profile_picture, ui.interest_ID
        FROM User u
        JOIN Profile p ON u.User_ID = p.User_ID
        LEFT JOIN User_Interest ui ON u.User_ID = ui.User_ID
        WHERE u.User_ID != %s
    """, (current_user.id,))
    all_rows = cursor.fetchall()

    # 3. Filter by interest (The "Algorithm")
    profiles_in_feed = []
    seen = set()
    for row in all_rows:
        i_id = row.get('interest_ID') or row.get('Interest_ID')
        if i_id and int(i_id) in my_interest_ids and row['User_ID'] not in seen:
            profiles_in_feed.append(row)
            seen.add(row['User_ID'])

    index = request.args.get('index', 0, type=int)
    display = None
    songs = [] # Initialize an empty list for songs

    # 4. FETCH THE MUSIC (Step 4)
    if index < len(profiles_in_feed):
        display = profiles_in_feed[index]
        # Now that we know WHO we are looking at, get their songs
        cursor.execute("SELECT * FROM Discography WHERE ID = %s", (display['User_ID'],))
        songs = cursor.fetchall()

    connection.close()

    return render_template(
        "matching.html.jinja", 
        profile=display, 
        songs=songs,      # Pass the tracks to the template
        next_index=index + 1
    )
@app.route('/invites')
@login_required
def view_invites():
    connection = connect_db()
    cursor = connection.cursor()
    
    # IMPORTANT: Mark all invites as 'seen' (1) now that the user is on the page
    cursor.execute("UPDATE invites SET seen = 1 WHERE User_2 = %s", (current_user.id,))
    
    # Fetch the info to display on the page
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

@app.route('/invites/<int:target_id>/send', methods=["POST"])
@login_required
def invites_send(target_id):
    connection = connect_db()
    cursor = connection.cursor()
    # We include 'seen=0' so the recipient gets a notification dot
    cursor.execute("INSERT INTO `invites` (`User_1`, `User_2`, `seen`) VALUES (%s, %s, 0)", (current_user.id, target_id))
    connection.close()
    flash("Invitation Sent!") 
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



@app.route('/profile_customization/upload_song', methods=["POST"])
@login_required
def upload_song():
    file = request.files.get("song_file")
    song_name = request.form.get("song_name")

    if file and allowed_file(file.filename):
        filename = secure_filename(f"track_{current_user.id}_{file.filename}")
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        connection = connect_db()
        cursor = connection.cursor()
        # Using the column names from your screenshot (ID = User ID, Song_name = filename)
        cursor.execute("""
            INSERT INTO `Discography` (`ID`, `Song_name`,`Song_file`) 
            VALUES (%s, %s, %s)
        """, (current_user.id, song_name, filename))
        connection.close()
        flash(f"Uploaded '{song_name}' to your discography!")
        #cursor.execute("SELECT * FROM `Discography` WHERE `ID` = %s",(current_user.id))
       # User_Discography = []
    
    return redirect(url_for('profile'))

@app.route('/delete_song/<int:song_id>', methods=["POST"])
@login_required
def delete_song(song_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM `Discography` WHERE `Song_ID` = %s AND `ID` = %s", (song_id, current_user.id))
    connection.close()
    flash("Track successfully removed.")
    return redirect(url_for('profile'))

@app.route('/invites/<int:user_id>/send', methods=['POST'])
def send_invite(user_id):
    
    
    
    flash("Invitation Sent!", "success") 
    
    next_index = request.args.get('index', 0)
    return redirect(url_for('matching', index=next_index))

@app.context_processor
def inject_notifications():
    if current_user.is_authenticated:
        connection = connect_db()
        cursor = connection.cursor()
        # Look for any invites where 'seen' is 0 for the logged-in user
        cursor.execute("SELECT COUNT(*) as count FROM invites WHERE User_2 = %s AND seen = 0", (current_user.id,))
        result = cursor.fetchone()
        connection.close()
        return dict(unread_notifications=(result['count'] > 0))
    return dict(unread_notifications=False)