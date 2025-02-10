from datetime import datetime

import MySQLdb
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_mysqldb import MySQL
from flask_wtf import FlaskForm
from wtforms import EmailField, StringField, PasswordField, SelectField, SubmitField, IntegerField
from wtforms.validators import DataRequired, Length, NumberRange
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message

app = Flask(__name__)


app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'  
app.config['MYSQL_PASSWORD'] = 'Password123!'  
app.config['MYSQL_DB'] = 'QuizzApp'
app.config['SECRET_KEY'] = 'your_secret_key'

mysql = MySQL(app)


class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=50)])
    email = EmailField('Email', validators=[DataRequired(), Length(min=5, max=100)]) 
    password = PasswordField('Password', validators=[DataRequired()])
    role = SelectField('Role', choices=[ ('test_taker', 'Test Taker')], validators=[DataRequired()])
    submit = SubmitField('Register')


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    role = SelectField('Role', choices=[ ('test_taker', 'Test Taker'),('admin', 'Admin')], validators=[DataRequired()])
    submit = SubmitField('Login')


class QuestionCountForm(FlaskForm):
    num_questions = IntegerField('Number of Questions', validators=[DataRequired(), NumberRange(min=1, max=20)])
    submit = SubmitField('Proceed')

@app.route("/", methods=["GET", "POST"])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        username = form.username.data
        email = form.email.data 
        password = form.password.data
        role = form.role.data

        hashed_password = generate_password_hash(password)  

        cur = mysql.connection.cursor()
        try:
            cur.execute("INSERT INTO users (username,email, password_hash, role) VALUES (%s, %s,%s, %s)",
                        (username,email, hashed_password, role))
            mysql.connection.commit()
            cur.close()

            session['username'] = username
            session['role'] = role
            
            flash("Registration successful!", "success")

            #if role == "admin":
                #return redirect(url_for('admin'))
            #else:
                #return redirect(url_for('test_taker_dashboard'))

        except:
            flash("Username already exists. Try another.", "danger")
            return redirect(url_for('register'))
    
    return render_template("register.html", form=form)

@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        role=form.role.data

        cur = mysql.connection.cursor()
        cur.execute("SELECT username, password_hash, role ,email FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        cur.close()

        if user:
            stored_role = user[2]  
            if check_password_hash(user[1], password):  
                if stored_role == role:  
                    session['username'] = user[0]
                    session['role'] = stored_role
                    session['admin_email'] = user[3] if stored_role == 'admin' else None
                    flash("Login successful!", "success")

                    if stored_role == 'admin':
                        return redirect(url_for('admin'))
                    else:
                        return redirect(url_for('test_taker_dashboard'))
                else:
                    flash("Incorrect role! Please log in with the correct role.", "danger")
            else:
                flash("Invalid username or password!", "danger")
        else:
            flash("User does not exist!", "danger")

    return render_template("login.html", form=form)

@app.route("/admin")
def admin():
    if 'username' in session and session.get('role') == 'admin':
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM tests WHERE created_by=%s", (session['username'],))

        tests = cur.fetchall()
        cur.close()
        return render_template("admin.html", username=session['username'], tests=tests)
    else:
        flash("Access denied! Admins only.", "danger")
        return redirect(url_for('login'))

@app.route("/test_taker_dashboard")
def test_taker_dashboard():
    if 'username' in session and session.get('role') == 'test_taker':
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)  
        cur.execute("""
            SELECT tests.test_id, tests.test_name
            FROM tests
            JOIN test_invitations ON tests.test_id = test_invitations.test_id
            WHERE test_invitations.username = %s
        """, (session['username'],))
        invited_tests = cur.fetchall()
        cur.close()
        current_time = datetime.now()

        
        return render_template("test_taker.html", username=session['username'], invited_tests=invited_tests)
    else:
        flash("Access denied! Test takers only.", "danger")
        return redirect(url_for('login'))



@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))



@app.route("/create_test", methods=["GET", "POST"])
def create_test():
    if "username" not in session or session.get("role") != "admin":
        flash("Access denied!", "danger")
        return redirect(url_for("login"))

    if request.method == "POST":
        test_name = request.form["test_name"]
        start_time = request.form["start_time"]
        end_time = request.form["end_time"]
        num_questions = request.form["num_questions"]

        try:
            start_time = datetime.strptime(start_time, "%Y-%m-%dT%H:%M")
            end_time = datetime.strptime(end_time, "%Y-%m-%dT%H:%M")
        except ValueError:
            flash("Invalid date format! Please use YYYY-MM-DD HH:MM.", "danger")
            return redirect(url_for("create_test"))

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM tests WHERE test_name = %s", (test_name,))
        existing_test = cur.fetchone()
        
        if existing_test:
            flash("A test with this name already exists!", "danger")
            return redirect(url_for("create_test"))
        
        cur.execute("""
            INSERT INTO tests (test_name, created_by, start_time, end_time, num_questions)
            VALUES (%s, %s, %s, %s, %s)
        """, (test_name, session["username"], start_time, end_time, num_questions))
        mysql.connection.commit()

        test_id = cur.lastrowid 
        cur.close()

        flash("Test created successfully!", "success")
        return redirect(url_for("add_questions", test_id=test_id, num_questions=num_questions))  

    return render_template("create_test.html")


@app.route("/add_questions", methods=["GET", "POST"])
def add_questions():
    if 'username' not in session or session.get('role') != 'admin':
        flash("Access denied!", "danger")
        return redirect(url_for('login'))

    test_id = request.args.get('test_id')  
    num_questions = int(request.args.get('num_questions', 1))  
    if request.method == "POST":
        cur = mysql.connection.cursor()
        for i in range(num_questions):
            question = request.form[f'question_{i}']
            option1 = request.form[f'option1_{i}']
            option2 = request.form[f'option2_{i}']
            option3 = request.form[f'option3_{i}']
            option4 = request.form[f'option4_{i}']
            correct_option = request.form[f'correct_option_{i}']

            if correct_option == 'option1':
                correct_option_index = 1
            elif correct_option == 'option2':
                correct_option_index = 2
            elif correct_option == 'option3':
                correct_option_index = 3
            elif correct_option == 'option4':
                correct_option_index = 4
            else:
                correct_option_index = 1  
            
            cur.execute("""
                INSERT INTO quizzes (test_id, question, option1, option2, option3, option4, correct_option)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (test_id, question, option1, option2, option3, option4, correct_option_index))

        mysql.connection.commit()
        cur.close()
        flash("Quiz Created Successfully!", "success")
        return redirect(url_for('admin'))

    return render_template("add_questions.html", num_questions=num_questions)



@app.route("/edit_test/<int:test_id>", methods=["GET", "POST"])
def edit_test(test_id):
    if 'username' not in session or session.get('role') != 'admin':
        flash("Access denied!", "danger")
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()

    
    cur.execute("SELECT * FROM tests WHERE test_id = %s", (test_id,))
    test = cur.fetchone()

    cur.execute("SELECT * FROM quizzes WHERE test_id=%s", (test_id,))
    questions = cur.fetchall()

    if request.method == "POST":
        updated_start_time = request.form['start_time']
        updated_end_time = request.form['end_time']

        
        cur.execute("""
            UPDATE tests
            SET start_time = %s, end_time = %s
            WHERE test_id = %s
        """, (updated_start_time, updated_end_time, test_id))

        
        option_map = {'option1': 1, 'option2': 2, 'option3': 3, 'option4': 4}

        for i, question in enumerate(questions):
            updated_question = request.form[f'question_{i}']
            updated_option1 = request.form[f'option1_{i}']
            updated_option2 = request.form[f'option2_{i}']
            updated_option3 = request.form[f'option3_{i}']
            updated_option4 = request.form[f'option4_{i}']
            updated_correct_option = request.form[f'correct_option_{i}']

            if updated_correct_option not in option_map:
                flash("Invalid correct option!", "danger")
                return redirect(url_for('edit_test', test_id=test_id))

            correct_option_value = option_map[updated_correct_option]

            cur.execute("""
                UPDATE quizzes
                SET question=%s, option1=%s, option2=%s, option3=%s, option4=%s, correct_option=%s
                WHERE test_id=%s AND id=%s
            """, (updated_question, updated_option1, updated_option2, updated_option3, updated_option4, correct_option_value, test_id, question[0]))

        mysql.connection.commit()
        cur.close()
        flash("Test updated successfully!", "success")
        return redirect(url_for('admin'))

    return render_template("edit_test.html", questions=questions, test=test)



@app.route("/invite_users/<int:test_id>", methods=["GET", "POST"])
def invite_users(test_id):
    """Allows admins to invite test takers to a test by linking directly."""
    if 'username' not in session or session.get('role') != 'admin':
        flash("Access denied!", "danger")
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()
    cur.execute("SELECT test_name FROM tests WHERE test_id=%s", (test_id,))
    test = cur.fetchone()

    cur.execute("SELECT username FROM users WHERE role='test_taker'")
    users = cur.fetchall()
    cur.close()

    if request.method == "POST":
        for user in users:
            cur = mysql.connection.cursor()
            cur.execute("INSERT INTO test_invitations (test_id, username) VALUES (%s, %s)", (test_id, user[0]))
            mysql.connection.commit()
            cur.close()
        
        flash(f"Users invited successfully for test: {test[0]}", "success")
        return redirect(url_for('admin'))

    return render_template("invite_users.html", test=test, users=users)


@app.route("/start_test/<int:test_id>", methods=["GET", "POST"])
def start_test(test_id):
    if 'username' not in session or session.get('role') != 'test_taker':
        flash("Access denied!", "danger")
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM quizzes WHERE test_id=%s", (test_id,))
    questions = cur.fetchall()
    print("Fetched questions:", questions)

    username = session.get("username")
    cur.execute("SELECT * FROM submissions WHERE username=%s AND test_id=%s", (username, test_id))
    existing_submission = cur.fetchone()

    if existing_submission:
        flash("You have already submitted this test. You can only view your score.", "info")
        return redirect(url_for("view_score", test_id=test_id))

    score = 0
    if request.method == "POST":
        for idx, question in enumerate(questions):
            correct_option = question[6]  
            selected_answer = request.form.get(f"question_{idx+1}")  

            
            if selected_answer == str(question[6]):
                score += 1
        
        
        username = session.get("username")
        cur.execute("SELECT * FROM submissions WHERE username=%s AND test_id=%s", (username, test_id))
        existing_submission = cur.fetchone()

        if existing_submission:
            cur.execute("""
                UPDATE submissions 
                SET score = %s, submitted_at = NOW() 
                WHERE username = %s AND test_id = %s
            """, (score, username, test_id))
            flash("Your test has been updated with the new score.", "info")
        else:
            cur.execute("""
                INSERT INTO submissions (username, test_id, score, submitted_at)
                VALUES (%s, %s, %s, NOW())
            """, (username, test_id, score))
            flash("Your test has been submitted successfully!", "success")

        mysql.connection.commit()

        return render_template("score.html", score=score, total=len(questions))

    cur.close()

    return render_template("start_test.html", test_id=test_id, questions=questions)


@app.route("/view_score/<int:test_id>")
def view_score(test_id):
    username = session.get("username")
    if not username:
        flash("Session expired. Please log in again.", "danger")
        return redirect(url_for("login"))

    cur = mysql.connection.cursor()

    cur.execute("SELECT score FROM submissions WHERE username=%s AND test_id=%s", (username, test_id))
    score_data = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM quizzes WHERE test_id = %s", (test_id,))
    total_questions = cur.fetchone()[0]

    cur.close()

    if score_data:
        return render_template("score.html", score=score_data[0], total=total_questions, test_id=test_id)
    else:
        flash("Test not submitted or not found!", "warning")
        return redirect(url_for("test_taker_dashboard"))



if __name__ == "__main__":
    app.run(debug=True)



