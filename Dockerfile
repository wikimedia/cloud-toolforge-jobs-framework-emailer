FROM debian:bullseye-slim
WORKDIR /
RUN apt-get update
RUN apt-get install python3-pip python3-wheel python3-setuptools -y --no-install-recommends
COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt
COPY . .
CMD [ "python3", "emailer.py" ]
