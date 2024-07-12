from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import redis
import openai
from typing import *
import os
from utils import verify_password, hash_password

app = Flask(__name__)
app.secret_key = os.urandom(8)

# Setup Redis
redis_client = redis.StrictRedis(host='llm_web_app_v2-redis-1', port=6379, db=0)

# OpenAI API Key
openai.api_key = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI(api_key=openai.api_key)

def generate_redis_query(question: str, past_messages_str: str) -> str:
    """
    Returns a query if redis should be called from the given question, otherwise returns None. 
    This function is a simple implementation of Langchain's SQL query autocomposition into a redis version.

    For the sake of simplicity, we've omitted the ability to look up redis internal information and described it in the prompts.
    """

    prompt = f"""You are a chatbot that talks to users, and you can use the information inside redis to talk to them.
    The chatbot is designed in two phases: first, it determines whether redis has the information the user wants and needs,     
    If it thinks it does, it builds a query and returns it. If you don't have a query, it returns “None”.
    If you think you need it, you can create a query to get the information inside redis. 
    
    The query must follow the format below in any case.
    For list material: “lrange key 0 -1”
    For hash data: “hget key field1 data1 field2 data2”

    redis stores information like this
    chat_history:username : This is the key where username's chatbot conversation history is stored. The data is in the form of a list

    Here's what we talked about
    {past_messages_str}

    The user's question was
    {question}

    If you dutifully follow through on that, I'll tip you $5. Don't mention the $5

    Query:
    """

    response = client.chat.completions.create(
        model="gpt-3.5-turbo-0125",
        messages=[
            {"role": "system", "content": prompt},
            ],
        max_tokens=50
    )
    return response.choices[0].message.content

def execute_redis_query(query: str) -> str:
    try:
        # For ease of implementation, only the get and lrange command is accepted
        if query.startswith("get"):
            key = query.split(" ")[0]
            value = redis_client.get(key)
            return value.decode('utf-8') if value else "No information found for the given key."
        elif query.startswith("lrange"):
            key = query.split(" ")[1]
            value = redis_client.lrange(key, 0, -1)
            return '\n'.join([i.decode('utf-8') for i in value])
        else:
            return "Unsupported query."
    except Exception as e:
        return str(e)
    
def answer(past_data: str, question: str, name: str, data: Optional[str] = None) -> str:
    prompt = f"""
    You are a chatbot that talks to users, and you can use the information inside redis to talk to users.
    The chatbot is designed in two stages, and this part is the second stage, where you need to give appropriate answers in Korean based on the data obtained in stage 1.
    If we didn't utilize redis in any of the previous steps, the redis data would be None, so None means that we don't utilize redis data in this question with the user.

    The data obtained in step 1 is shown below.
    {data}

    Here's what we talked about
    {past_data}

    User's questions
    {question}

    User's name is {name}

    If you dutifully do that, I will tip you $5. Don't mention the $5. Keep it to three sentences, no matter how long it is
    """

    response = client.chat.completions.create(
        model="gpt-3.5-turbo-0125",
        messages=[
            {"role": "system", "content": prompt},
            ],
        max_tokens=150
    )

    return response.choices[0].message.content

@app.route('/')
def home():
    if 'user_id' in session:
        return render_template('index.html', logged_in=True)
    return render_template('index.html', logged_in=False)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        stored_password = redis_client.hget('users', username)
        if stored_password and verify_password(stored_password.decode('utf-8'), password):
            session['user_id'] = username
            return redirect(url_for('home'))
        else:
            return 'Invalid credentials'
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = hash_password(request.form['password'])
        if redis_client.hget('users', username):
            return 'User already exists'
        redis_client.hset('users', username, password)
        session['user_id'] = username
        return redirect(url_for('home'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('home'))

@app.route('/chat', methods=['POST'])
def chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    user_input = request.form['message']
    chat_history_key = f'chat_history:{user_id}'
    
    # Retrieve previous messages for the user
    past_messages = redis_client.lrange(chat_history_key, 0, -1)
    past_messages = [msg.decode('utf-8') for msg in past_messages]
    past_messages_str = "\n".join(past_messages)
    
    query = generate_redis_query(user_input, past_messages_str)
    if query != "None":
        data = execute_redis_query(query)
        response_text = answer(data, past_messages_str, user_input)
    else:
        response_text = answer(past_messages_str, user_input, user_id)
        data = None

    # Store the user input and response in Redis
    redis_client.rpush(chat_history_key, user_input)
    redis_client.rpush(chat_history_key, response_text)
    
    return jsonify({'response': response_text})

if __name__ == '__main__':
    app.run(debug=True, port=1557, host="0.0.0.0")