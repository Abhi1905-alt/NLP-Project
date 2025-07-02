from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from models import db, User, Generation
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch
import re

def remove_repetition(text):
    sentences = re.split(r'(?<=[.!?]) +', text.strip())
    seen = set()
    unique_sentences = []
    for sentence in sentences:
        clean_sentence = sentence.strip()
        if clean_sentence not in seen:
            seen.add(clean_sentence)
            unique_sentences.append(clean_sentence)
    return '\n\n'.join(unique_sentences)

app = Flask(__name__)           

app.secret_key = 'supersecretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db.init_app(app)
bcrypt = Bcrypt(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# Load model and tokenizer 
device = "cuda" if torch.cuda.is_available() else "cpu"
tokenizer = AutoTokenizer.from_pretrained("google/flan-t5-large")
model = AutoModelForSeq2SeqLM.from_pretrained("google/flan-t5-large").to(device)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'error')
        else:
            user = User(username=username, password=password)
            db.session.add(user)
            db.session.commit()
            flash('Account created. Please login.', 'success')
            return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and bcrypt.check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid credentials', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    output_text = ""
    if request.method == 'POST':
        prompt = request.form['prompt'].strip()
        task_type = request.form['task']
        style = request.form.get('style', 'formal')  # default to formal if not specified

        if task_type == 'email':
            full_prompt = (
                f"You are an assistant that writes professional emails. Generate a clear, polite, and concise email on the following topic:\n\n"
                f"{prompt}\n\n"
                "Include a greeting, a brief body with important details, and a formal closing."
            )
        else:  # article
            style_instruction = ""
            if style == 'blog':
                style_instruction = " Write this article in a casual and engaging blog tone."
            elif style == 'explainer':
                style_instruction = " Use an educational tone suitable for students or general readers."
            elif style == 'narrative':
                style_instruction = " Use storytelling to make the content engaging."
            else:  # formal or default
                style_instruction = " Use a formal and informative tone."

            full_prompt = (
                f"You are a professional writer. Write a full-length article on the topic:\n\n"
                f"\"{prompt}\".\n\n"
                f"The article should be clear, informative, and avoid vague or generic statements.{style_instruction} "
                "Do not describe what each paragraph will be about. Just write the article naturally."
            )

        inputs = tokenizer(full_prompt, return_tensors="pt", truncation=True).to(device)

        outputs = model.generate(
            **inputs,
            max_new_tokens=640,
            temperature=0.7,
            top_p=0.9,
            repetition_penalty=1.4,
            no_repeat_ngram_size=4,
            num_return_sequences=1,
            do_sample=True,
            early_stopping=True,
        )

        raw_text = tokenizer.decode(outputs[0], skip_special_tokens=True).strip()
        cleaned_text = remove_repetition(raw_text)
        output_text = "\n".join([line for line in cleaned_text.splitlines() if line.strip()])

        generation = Generation(prompt=prompt, output=output_text, task_type=task_type, user_id=current_user.id)
        db.session.add(generation)
        db.session.commit()

    return render_template('index.html', output=output_text)

@app.route('/history')
@login_required
def history():
    user_history = Generation.query.filter_by(user_id=current_user.id).order_by(Generation.id.desc()).all()
    return render_template('history.html', history=user_history)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

