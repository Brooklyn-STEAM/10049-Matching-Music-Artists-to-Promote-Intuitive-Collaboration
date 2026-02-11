from flask import Flask, render_template,redirect,abort,request,url_for,flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import check_password_hash


import pymysql

from dynaconf import Dynaconf

app = Flask(__name__)


config = Dynaconf(settings_file = [ "settings.toml" ])
@app.route("/")
def index():
   return render_template("index.html.jinja")

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



