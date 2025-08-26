# Use the official Python slim image
FROM python:3.11-slim

USER root

# Install system dependencies including Tkinter, Xvfb, and X11 utilities
RUN apt update && apt install -y \
    git \
    tk \
    tcl \
    libx11-6 \
    libxrender-dev \
    libxext-dev \
    libxinerama-dev \
    libxi-dev \
    libxrandr-dev \
    libxcursor-dev \
    libxtst-dev \
    tk-dev \
    xvfb \
    x11-apps \
    x11vnc \
    fluxbox \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

RUN     mkdir ~/.vnc
RUN     x11vnc -storepasswd 1234 ~/.vnc/passwd

# Copy only requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --break-system-packages --no-cache-dir -r requirements.txt

# Then copy the rest of the app
COPY . .

# Set the DISPLAY environment variable for Xvfb
ENV DISPLAY=:99

# Expose the VNC port
EXPOSE 5990

# Set the entrypoint to automatically run the script
ENTRYPOINT ["bash", "/app/start.sh"]
