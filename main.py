from flask import Flask, render_template, redirect, abort, request, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
import os 
import pymysql
from dynaconf import Dynaconf
import random 
from flask import session

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


@app.route('/interest', methods=["POST"])
@login_required
def update_interests():
    selected_interests = request.form.getlist('interest')  # Get selected interest IDs
    connection = connect_db()
    cursor = connection.cursor()

    # Clear existing interests for the user
    cursor.execute("DELETE FROM User_Interest WHERE User_ID = %s", (current_user.id,))

    # Insert new interests
    for interest_id in selected_interests:
        cursor.execute("INSERT INTO User_Interest (User_ID, Interest_ID) VALUES (%s, %s)", (current_user.id, interest_id))

    connection.close()
    flash("Interests updated successfully!")
    return redirect(url_for('profile'))

@app.route('/profile_customization', methods=["GET", "POST"])
@login_required
def profile_settings():
    connection = connect_db()
    cursor = connection.cursor()

    if request.method == 'POST':
        profile_name = request.form["Profile_name"]
        description = request.form["description"]
        file = request.files.get("Profile_picture")

        # Keep old picture if no new one is uploaded
        cursor.execute("SELECT Profile_picture FROM Profile WHERE User_ID = %s", (current_user.id,))
        current_pfp = cursor.fetchone()
        filename = current_pfp['Profile_picture'] if current_pfp else "default"

        if file and allowed_file(file.filename):
            filename = secure_filename(f"user_{current_user.id}_{file.filename}")
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        cursor.execute("""
            UPDATE `Profile`
            SET `Profile_name` = %s, `Profile_picture` = %s, `description` = %s
            WHERE `User_ID` = %s
        """, (profile_name, filename, description, current_user.id))
        
        flash("Profile has been updated successfully!") 
        connection.commit() # Make sure changes are saved
        connection.close()
        return redirect(url_for('profile'))

    # --- GET REQUEST LOGIC ---
    
    # 1. Fetch the current user's profile
    cursor.execute('SELECT * FROM `Profile` WHERE `User_ID` = %s', (current_user.id,))
    profile_data = cursor.fetchone()

    # 2. Fetch all possible interests for the checkbox list
    cursor.execute('SELECT * FROM `Interest`')
    interests = cursor.fetchall()

    # 3. Fetch the names of blacklisted users
    cursor.execute("""
        SELECT u.User_ID, p.Profile_name 
        FROM Dislikes d
        JOIN User u ON d.Target_ID = u.User_ID
        JOIN Profile p ON u.User_ID = p.User_ID
        WHERE d.User_ID = %s
    """, (current_user.id,))
    blacklisted_users = cursor.fetchall()
    
    connection.close()
    
    return render_template(
        "profile_customization.html.jinja", 
        Interest=interests, 
        Profile=profile_data, 
        Blacklist=blacklisted_users
    )


@app.route("/matching")
@login_required
def matching():
    connection = connect_db()
    cursor = connection.cursor()
    
    # 1. Fetch current user's interest IDs
    cursor.execute("SELECT Interest_ID FROM User_Interest WHERE User_ID = %s", (current_user.id,))
    my_interest_ids = [row['Interest_ID'] for row in cursor.fetchall()]

    if not my_interest_ids:
        connection.close()
        return render_template("matching.html.jinja", profile=None, songs=[])

    # 2. Fetch EVERYONE who shares at least one of those interests
    cursor.execute("""
        SELECT DISTINCT u.User_ID, p.Profile_name, p.description, p.Profile_picture
        FROM User u
        JOIN Profile p ON u.User_ID = p.User_ID
        JOIN User_Interest ui ON u.User_ID = ui.User_ID
        WHERE u.User_ID != %s 
        AND ui.Interest_ID IN %s
    """, (current_user.id, tuple(my_interest_ids)))
    
    all_eligible_matches = cursor.fetchall()

    display = None
    songs = []

    # 3. Pick exactly ONE random person from that pool
    if all_eligible_matches:
        display = random.choice(all_eligible_matches)
        
        # 4. Fetch the songs for that specific random person
        cursor.execute("SELECT * FROM Discography WHERE ID = %s", (display['User_ID'],))
        songs = cursor.fetchall()

    connection.close() 
    
    return render_template("matching.html.jinja", profile=display, songs=songs)


@app.route('/invites')
@login_required
def view_invites():
    connection = connect_db()
    cursor = connection.cursor()
    
    # Mark all invites as 'seen'
    cursor.execute("UPDATE invites SET seen = 1 WHERE User_2 = %s", (current_user.id,))
    
    # Fetch invites
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


# --- NEW: DETAILED PROFILE REVIEW ROUTE ---
@app.route('/invites/<int:sender_id>/review')
@login_required
def review_invite_profile(sender_id):
    connection = connect_db()
    cursor = connection.cursor()
    
    # 1. Safety verification check
    cursor.execute("SELECT 1 FROM invites WHERE User_1 = %s AND User_2 = %s", (sender_id, current_user.id))
    invite_exists = cursor.fetchone()
    
    if not invite_exists:
        connection.close()
        abort(404)

    # 2. Fetch Target Profile Info
    cursor.execute('SELECT * FROM `Profile` WHERE `User_ID` = %s', (sender_id,))
    profile_data = cursor.fetchone()

    # 3. Fetch Target Interests
    cursor.execute("""
        SELECT Interest.name, Interest.interest_ID
        FROM User_Interest
        JOIN Interest ON User_Interest.interest_ID = Interest.interest_ID
        WHERE User_Interest.User_ID = %s
    """, (sender_id,))
    user_interests = cursor.fetchall()

    # 4. Fetch Target Songs
    cursor.execute('SELECT * FROM `Discography` WHERE `ID` = %s', (sender_id,))
    songs = cursor.fetchall()
    
    connection.close()
        
    return render_template(
        "review_profile.html.jinja", 
        Profile=profile_data, 
        Songs=songs, 
        user_interests=user_interests,
        sender_id=sender_id
    )


@app.route('/invites/<int:target_id>/send', methods=["POST"])
@login_required
def invites_send(target_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("INSERT INTO `invites` (`User_1`, `User_2`) VALUES (%s, %s)", (current_user.id, target_id))
    cursor.execute("SELECT * FROM `Discography` WHERE `ID` = %s",(target_id))
    songs = cursor.fetchall()
    flash("Invitation Sent!")
    connection.close()
    return redirect(url_for('matching'))


@app.route('/invites/<int:sender_id>/accept', methods=["POST"])
@login_required
def accept_invite(sender_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("INSERT INTO `Matches` (`User_1`, `User_2`) VALUES (%s, %s)", (sender_id, current_user.id))
    cursor.execute("DELETE FROM `invites` WHERE `User_1` = %s AND `User_2` = %s", (sender_id, current_user.id))
    connection.close()
    return redirect(url_for('view_invites'))

@app.route('/invites/<int:sender_id>/decline', methods=["POST"])
@login_required
def decline_invite(sender_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM `invites` WHERE `User_1` = %s AND `User_2` = %s", (sender_id, current_user.id))
    connection.close()
    return redirect(url_for('view_invites'))


@app.route('/dislike/<int:target_id>', methods=["POST"])
@login_required
def dislike_user(target_id):
    connection = connect_db()
    cursor = connection.cursor()
    try:
        cursor.execute("INSERT IGNORE INTO Dislikes (User_ID, Target_ID) VALUES (%s, %s)", 
                       (current_user.id, target_id))
        flash("Artist added to Blacklist. You can manage this in settings.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        connection.close()
    
    return redirect(url_for('matching'))

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
        cursor.execute("""
            INSERT INTO `Discography` (`ID`, `Song_name`,`Song_file`) 
            VALUES (%s, %s, %s)
        """, (current_user.id, song_name, filename))
        connection.close()
        flash(f"Uploaded '{song_name}' to your discography!")
    
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
    return redirect(url_for('matching'))


@app.context_processor
def inject_notifications():
    if current_user.is_authenticated:
        connection = connect_db()
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM invites WHERE User_2 = %s AND seen = 0", (current_user.id,))
        result = cursor.fetchone()
        connection.close()
        return dict(unread_notifications=(result['count'] > 0))
    return dict(unread_notifications=False)


@app.route('/remove_blacklist/<int:target_id>', methods=["POST"])
@login_required
def remove_blacklist(target_id):
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM Dislikes WHERE User_ID = %s AND Target_ID = %s", (current_user.id, target_id))
    connection.close()
    flash("Artist removed from Blacklist!")
    return redirect(url_for('profile_settings'))

@app.route("/chat/<User_ID>")
@login_required
def chatroom(User_ID):
    chat_log = []
    
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute(""" 
    SELECT User.User_ID, Profile.ID, Profile.Profile_name, Profile.Profile_picture
    FROM User
    JOIN Profile ON User.User_ID = Profile.ID
    WHERE User.User_ID = %s 
    """,(User_ID))
    individual_chat_room = cursor.fetchone()

    # the preiviously sent messages
    cursor.execute("SELECT * FROM `messages` WHERE (`sender` = %s AND `receiver` = %s)",(current_user.id, User_ID))
    current_user_messages = cursor.fetchall()

    cursor.execute("SELECT * FROM `messages` WHERE (`receiver` = %s AND `sender` = %s)",(current_user.id, User_ID))
    User_messages = cursor.fetchall()
    
    chat_log.extend(current_user_messages)
    chat_log.extend(User_messages)
    connection.close()
    return render_template("chat.html.jinja",chatroom=individual_chat_room, sender_message=current_user_messages, receiver_messages=User_messages, chat_log=chat_log )

@app.route("/chat/<User_ID>/send", methods=["POST", "GET"])
@login_required
def send_message(User_ID):
    if request.method == 'POST':
        message = request.form["message"]
        connection = connect_db()
        cursor = connection.cursor()
        cursor.execute("INSERT INTO `messages` (`sender`,`receiver`,`message`) VALUES(%s, %s, %s)",(current_user.id, User_ID, message))
        connection.close()
    
    return render_template("chat.html.jinja")

@app.route('/view_profile/<int:user_id>')
@login_required
def view_profile(user_id):
    connection = connect_db()
    cursor = connection.cursor()

    
    cursor.execute("SELECT * FROM Profile WHERE User_ID = %s", (user_id,))
    profile_data = cursor.fetchone()

    if not profile_data:
        connection.close()
        abort(404)  


   
    cursor.execute("""
        SELECT Interest.name 
        FROM User_Interest
        JOIN Interest ON User_Interest.interest_ID = Interest.interest_ID
        WHERE User_Interest.User_ID = %s
    """, (user_id,))
    user_interests = cursor.fetchall()

   
    cursor.execute("SELECT * FROM Discography WHERE ID = %s", (user_id,))
    user_songs = cursor.fetchall()

    connection.close()

    return render_template(
        "view_profile.html.jinja",
        Profile = profile_data,
        Interests = user_interests,
        Songs = user_songs
    )

