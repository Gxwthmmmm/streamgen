FROM python:3.11-slim
WORKDIR /app
COPY ml-service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY ml-service/app ./app
COPY data ./data
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
