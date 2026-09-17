import os
import random
from datetime import datetime

from flask import Flask, redirect, render_template, request, session, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from functools import wraps
# Next line added to fix proxy issues on Azure - see line 21.
from werkzeug.middleware.proxy_fix import ProxyFix
import msal
import uuid
import os


app = Flask(__name__)
# Azure App Service terminates TLS and forwards plain HTTP to the container,
# so trust the X-Forwarded-Proto/Host headers to build correct https:// URLs.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///chatrooms.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = os.environ.get('TENANT_ID', 'common') # I believe flask uses this to sign session cookies and that it should be the SECRET_KEY from .env.example

# ── Microsoft Entra ID Configuration ─────────────────────────
CLIENT_ID     = os.environ.get('CLIENT_ID')
CLIENT_SECRET = os.environ.get('CLIENT_SECRET')
TENANT_ID     = os.environ.get('TENANT_ID', 'common')
AUTHORITY     = f'https://login.microsoftonline.com/{TENANT_ID}'
SCOPE         = ['User.Read']   # Ask for permission to read the user's profile

# Removed when adding Entra ID code. p. 7 of the instructions.
#app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

db = SQLAlchemy(app)
migrate = Migrate(app, db)


# ── Models ────────────────────────────────────────────────────────────────────

class Room(db.Model):
    __tablename__ = "rooms"
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(120), nullable=False, unique=True)
    created_by = db.Column(db.String(80),  nullable=False)
    created_at = db.Column(db.DateTime,    default=datetime.utcnow)
    messages   = db.relationship(
        "Message", backref="room", lazy="dynamic",
        cascade="all, delete-orphan"
    )

    @property
    def message_count(self):
        return self.messages.count()

    @property
    def last_activity(self):
        last = self.messages.order_by(Message.posted_at.desc()).first()
        return last.posted_at if last else self.created_at


class Message(db.Model):
    __tablename__ = "messages"
    id        = db.Column(db.Integer, primary_key=True)
    room_id   = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False)
    author    = db.Column(db.String(80), nullable=False)
    content   = db.Column(db.Text,      nullable=False)
    posted_at = db.Column(db.DateTime,  default=datetime.utcnow)


# ── Nickname helper ───────────────────────────────────────────────────────────

ADJECTIVES = [
    "Blue","Red","Green","Silver","Golden","Swift","Bold","Calm",
    "Dark","Bright","Cool","Wild","Lazy","Happy","Fierce","Gentle",
    "Clever","Brave","Quiet","Loud","Fuzzy","Shiny","Speedy","Tiny",
]
ANIMALS = [
    "Fox","Wolf","Bear","Eagle","Hawk","Lion","Tiger","Panda",
    "Otter","Deer","Owl","Raven","Shark","Whale","Lynx","Moose",
    "Bison","Crane","Cobra","Gecko","Falcon","Badger","Ferret","Marmot",
]

def get_nickname():
    if "nickname" not in session:
        adj    = random.choice(ADJECTIVES)
        animal = random.choice(ANIMALS)
        num    = random.randint(10, 99)
        session["nickname"] = f"{adj}{animal}{num}"
    return session["nickname"]


# —— MSAL Helper function ——————————————————————————————————————————————————————

def _build_msal_app():
    """Create an MSAL ConfidentialClientApplication instance."""
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )

def login_required(f):
    """Decorator: redirect to Microsoft login if user is not in session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            # Save where the user was trying to go
            session['next'] = request.url
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# ── Routes ────────────────────────────────────────────────────────────────────

# MSAL Login route
@app.route('/login')
def login():
    """Redirect the user to Microsoft's login page."""
    # Generate a random state value to prevent CSRF attacks
    session['state'] = str(uuid.uuid4())

    auth_url = _build_msal_app().get_authorization_request_url(
        SCOPE,
        state=session['state'],
        redirect_uri=url_for('callback', _external=True)
    )
    return redirect(auth_url)

@app.route('/callback')
def callback():
    """Microsoft redirects here after the user logs in."""

    # Security check: verify the state matches to prevent CSRF
    if request.args.get('state') != session.get('state'):
        return redirect(url_for('index'))

    # Check if Microsoft returned an error (e.g. user cancelled login)
    if 'error' in request.args:
        error_msg = request.args.get('error_description', request.args.get('error'))
        return f'<h2>Login Error</h2><p>{error_msg}</p><a href="/">Return home</a>'

    # Exchange the authorization code for an ID token
    result = _build_msal_app().acquire_token_by_authorization_code(
        request.args['code'], 
        scopes=SCOPE,
        redirect_uri=url_for('callback', _external=True)
    )

    if 'error' in result:
        return f'<h2>Token Error</h2><p>{result.get("error_description")}</p>'

    # Store the token claims in the session (contains name, email, etc.)
    session['user'] = result.get('id_token_claims')
    session['nickname'] = session['user'].get('preferred_username')

    # Redirect to where the user was trying to go, or the home page
    next_page = session.pop('next', None)
    return redirect(next_page or url_for('index'))

@app.route('/logout')
def logout():
    """Clear the local session and sign out of Microsoft."""
    session.clear()
    # Redirect to Microsoft's logout endpoint so the browser session is fully cleared
    logout_url = (
        AUTHORITY
        + '/oauth2/v2.0/logout'
        + '?post_logout_redirect_uri='
        + url_for('index', _external=True)
    )
    return redirect(logout_url)


@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    nickname = get_nickname()
    error = None
    if request.method == "POST":
        name = request.form.get("room_name", "").strip()
        if name:
            existing = Room.query.filter_by(name=name).first()
            if existing:
                return redirect(url_for("room", room_id=existing.id))
            new_room = Room(name=name, created_by=nickname)
            db.session.add(new_room)
            db.session.commit()
            return redirect(url_for("room", room_id=new_room.id))
        error = "Room name cannot be empty."
    rooms = Room.query.order_by(Room.created_at.desc()).all()
    return render_template("index.html", rooms=rooms, nickname=nickname, error=error)

@app.route("/room/<int:room_id>", methods=["GET", "POST"])
@login_required
def room(room_id):
    r        = Room.query.get_or_404(room_id)
    nickname = get_nickname()
    if request.method == "POST":
        content = request.form.get("content", "").strip()
        if content:
            msg = Message(room_id=room_id, author=nickname, content=content)
            db.session.add(msg)
            db.session.commit()
        return redirect(url_for("room", room_id=room_id))
    messages = r.messages.order_by(Message.posted_at.asc()).limit(50).all()
    return render_template("room.html", room=r, messages=messages, nickname=nickname)


if __name__ == "__main__":
    app.run(debug=True)
