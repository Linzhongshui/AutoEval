FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
    && rm -f /etc/ssh/ssh_host_* \
    && mkdir -p /run/sshd
LABEL autoeval.role=ssh-simulator
EXPOSE 22
# Keep sshd as the supervised foreground process so container restart restores SSH.
CMD ["sh", "-c", "ssh-keygen -A && mkdir -p /run/sshd && exec /usr/sbin/sshd -D -e -o PasswordAuthentication=no -o PermitRootLogin=no"]
