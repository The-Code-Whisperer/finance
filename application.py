import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("postgres://yqdndxamedwlgp:2421c3f50b42b6a847bb81bbd4244f6545f721409bfc17120374b3f78d2bc2cf@ec2-174-129-253-28.compute-1.amazonaws.com:5432/d5vepq69vlebg1")
#db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    id = session["user_id"]
    username = db.execute("SELECT username FROM users WHERE id=?", id)[0]["username"]
    transactions = db.execute("SELECT * FROM transactions WHERE username=?", username)
    cash = db.execute("SELECT cash FROM users WHERE id=?", id)[0]["cash"]
    net = cash
    portfolio = {}
    for transaction in transactions:
        symbol = transaction["symbol"]
        if symbol not in portfolio.keys():
            portfolio[symbol] = {}
            portfolio[symbol]["price"] = lookup(symbol)["price"]
            if transaction["type"] == "BUY":
                portfolio[symbol]["name"] = lookup(symbol)["name"]
                portfolio[symbol]["shares_bought"] = transaction["quantity"]
                portfolio[symbol]["value_bought"] = transaction["total"]
                portfolio[symbol]["shares_owned"] = transaction["quantity"]
                portfolio[symbol]["value_owned"] = transaction["quantity"] * portfolio[symbol]["price"]
                portfolio[symbol]["avg_pur_price"] = transaction["price"]
            elif transaction["type"] == "SELL":
                portfolio[symbol]["shares_owned"] = -transaction["quantity"]
                portfolio[symbol]["value_owned"] = -transaction["quantity"] * portfolio[symbol]["price"]
            else:
                return render_template("Database error. Contact Steven.")
        else:
            if transaction["type"] == "BUY":
                portfolio[symbol]["avg_pur_price"] = (portfolio[symbol]["avg_pur_price"] * portfolio[symbol]["shares_bought"]
                                                      + transaction["quantity"] * transaction["price"]) / (portfolio[symbol]["shares_bought"] + transaction["quantity"])
                portfolio[symbol]["shares_bought"] += transaction["quantity"]
                portfolio[symbol]["value_bought"] += transaction["total"]
                portfolio[symbol]["shares_owned"] += transaction["quantity"]
                portfolio[symbol]["value_owned"] += transaction["quantity"] * portfolio[symbol]["price"]
            elif transaction["type"] == "SELL":
                portfolio[symbol]["shares_owned"] -= transaction["quantity"]
                portfolio[symbol]["value_owned"] -= transaction["quantity"] * portfolio[symbol]["price"]
            else:
                return render_template("Database error. Contact Steven.")
    for data_dict in portfolio.values():
        net += data_dict["shares_owned"] * data_dict["price"]
    return render_template("index.html", portfolio=portfolio, cash=cash, net=net)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":
        # set variables
        id = session["user_id"]
        username = db.execute("SELECT username FROM users WHERE id=:id", id=id)[0]["username"]
        symbol = request.form.get("symbol").upper()
        # check for invalid ticker
        if lookup(symbol):
            price = lookup(symbol)["price"]
        else:
            return apology("That stock symbol does not exist. Look them up online.")
        try:
            quantity = float(request.form.get("shares"))
        except ValueError:
            return apology("That's a weird number of shares.")
        if not quantity > 0 or round(quantity % 1, 3) != 0:
            return apology("That's a weird number of shares.")
        total = price * quantity
        cash = db.execute("SELECT cash FROM users WHERE id=:id", id=id)[0]["cash"]
        if cash > total:
            db.execute("INSERT INTO transactions \
                (username, symbol, price, quantity, total, type) \
                VALUES (?, ?, ?, ?, ?, ?)", username, symbol, price, quantity, total, "BUY")
            cash = round(cash - total, 2)
            db.execute("UPDATE users SET cash=:cash WHERE id=:id", cash=cash, id=id)
            return redirect("/")
        else:
            return apology("You do not have enough money for that purchase!")
    else:
        return render_template("buy.html")


@app.route("/leaderboard")
@login_required
def leaderboard():
    """Show leaderboard."""
    username_list_dicts = db.execute("SELECT username FROM users")
    usernames = []
    user_nets = {}
    for i in range(len(username_list_dicts)):
        if username_list_dicts[i]["username"] not in usernames:
            usernames.append(username_list_dicts[i]["username"])
    for username in usernames:
        # find net worth of username
        transactions = db.execute("SELECT * FROM transactions WHERE username=?", username)
        net = db.execute("SELECT cash FROM users WHERE username=?", username)[0]["cash"]
        for transaction in transactions:
            if transaction["type"] == "BUY":
                net += transaction["quantity"] * lookup(transaction["symbol"])["price"]
            else:
                net -= transaction["quantity"] * lookup(transaction["symbol"])["price"]
        user_nets[username] = net
    leaderboard = []
    for user, net in user_nets.items():
        leaderboard.append({"user": user, "net": net})
    leaderboard = sorted(leaderboard, key=lambda i: i['net'], reverse=True)
    return render_template("leaderboard.html", leaderboard=leaderboard)


@app.route("/check", methods=["GET"])
def check():
    """Return true if username available, else false, in JSON format"""
    username = request.args.get("username")
    if len(username) < 1 or db.execute("SELECT * FROM users WHERE username=:username",
                                       username=username):
        return jsonify(False)
    return jsonify(True)


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    # return list of transaction dictionaries
    username = db.execute("SELECT username FROM users WHERE id=:id", id=session["user_id"])[0]["username"]
    transactions = db.execute("SELECT * FROM transactions WHERE username=:username",
                              username=username)
    return render_template("history.html", transactions=transactions)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""
    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        # Forget any user_id
        session.clear()
        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username=:username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        # retrieve stock quote
        stock = lookup(request.form.get("symbol"))
        if stock:
            return render_template("display.html", name=stock["name"], price=stock["price"],
                                   symbol=stock["symbol"])
        # if stock quote exists display it, otherwise apologize
        else:
            return apology("That symbol does not correspond to any stock.")
    else:
        # display form
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    # Query database for username
    rows = db.execute("SELECT * FROM users")
    # If form was posted
    if request.method == "POST":
        # if username is blank, return apology
        if not request.form.get("username"):
            return apology("Missing username!")
        # if password is blank, return apology
        elif not request.form.get("password") or not request.form.get("confirmation"):
            return apology("Missing password!")
        # if passwords do not match
        elif request.form.get("password") != request.form.get("confirmation"):
            return apology("Passwords do not match!")
        # if username already exists in db, return apology
        elif db.execute("SELECT * FROM users WHERE username=:username",
                        username=request.form.get("username")):
            return apology("Username taken.")
        # register the new user
        else:
            # hash password before storing using pwd_context.encrypt
            hash = generate_password_hash(request.form.get("password"))
            # add user to database
            result = db.execute("INSERT INTO users (username, hash) VALUES(:username, :hash)",
                                username=request.form.get("username"), hash=hash)
            # this error should not happen because we already checked to make sure
            # it is a unique username, but if it does, return a database error.
            if not result:
                return apology("Database error.")
            # login user automatically after registering
            rows = db.execute("SELECT * FROM users WHERE username=:username",
                              username=request.form.get("username"))
            session["user_id"] = rows[0]["id"]
            return redirect("/")
    # if going to register page without posting form
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():  # receive symbol, shares
    """Sell shares of stock"""
    id = session["user_id"]
    username = db.execute("SELECT username FROM users WHERE id=:id", id=id)[0]["username"]
    if request.method == "POST":
        symbol = request.form.get("symbol").upper()
        if lookup(symbol):
            price = lookup(symbol)["price"]
        else:
            apology("That stock doesn't exist.")
        # get number of shares being sold
        quantity = float(request.form.get("shares"))
        if not quantity > 0 or round(quantity % 1, 3) != 0:
            apology("That's a weird number of shares.")
        total = quantity * price
        # find shares owned
        transactions = db.execute("SELECT * FROM transactions WHERE username=:username AND symbol=:symbol",
                                  username=username, symbol=symbol)
        shares_owned = 0
        for transaction in transactions:
            shares_owned += transaction["quantity"]
        # sell only if user has enough shares
        if shares_owned >= quantity:
            # update shares owned into transactions
            db.execute("INSERT INTO transactions (username, symbol, price, quantity, total, type) \
                       VALUES (:username, :symbol, :price, :quantity, :total, :type)", username=username,
                       symbol=symbol, price=price, quantity=quantity, total=total, type="SELL")
            # update cash
            cash = db.execute("SELECT cash FROM users WHERE id=:id", id=id)[0]["cash"]
            cash += total
            db.execute("UPDATE users SET cash=:cash WHERE id=:id", cash=cash, id=id)
            return redirect("/")
        else:
            return apology("You don't have enough shares to sell that many!")
    else:
        # return sell.html with list of sellable symbols
        stocks = db.execute("SELECT symbol FROM transactions WHERE username=? AND quantity!=?",
                            username, 0)
        symbols = []
        for transaction in stocks:
            symbols.append(transaction["symbol"])
        symbols = list(dict.fromkeys(symbols))
        return render_template("sell.html", symbols=symbols)


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
