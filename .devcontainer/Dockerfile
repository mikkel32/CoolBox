FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install Tk for CustomTkinter
RUN apt-get update && \
    apt-get install -y tk git && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt debugpy

WORKDIR /workspace

CMD ["bash"]
