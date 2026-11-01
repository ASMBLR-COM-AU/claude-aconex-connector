FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY gateway ./gateway
# Run as a normal user, not root.
RUN useradd --create-home gateway
USER gateway
EXPOSE 8080
CMD ["python", "-m", "gateway"]
