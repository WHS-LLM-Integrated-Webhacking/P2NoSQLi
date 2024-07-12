FROM python:3.9-slim

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

ENV OPENAI_API_KEY=OPENAI_API_KEY

ENTRYPOINT ["python", "app.py"]