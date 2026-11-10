FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
    && rm -f /etc/ssh/ssh_host_* \
    && mkdir -p /run/sshd
LABEL autoeval.role=ssh-simulator
EXPOSE 22
# setup_ssh_sim.py enrolls a development public key and starts sshd after key generation.
CMD ["sh", "-c", "ssh-keygen -A && python -c 'import time; time.sleep(31536000)'"]
