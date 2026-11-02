FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY gateway ./gateway
# Starts as root only to hand the storage volume to the `gateway` user, then
# switches to that user before serving anything (see gateway/__main__.py).
RUN useradd --create-home gateway
EXPOSE 8080
CMD ["python", "-m", "gateway"]
