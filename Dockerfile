FROM python:3.12-slim

WORKDIR /app

# Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app code
COPY app/ /app/

# Copy the shared swarm-oversight package (parent directory)
# The swarm-oversight repo is at ../swarm-oversight relative to Twin/
COPY ../swarm-oversight/ /app/swarm-oversight/

# Default env (override at runtime)
ENV PAYPAL_CLIENT_ID="" \
    PAYPAL_SECRET=""

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]