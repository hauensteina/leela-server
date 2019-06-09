
A back end API to ask leela for moves and run a keras scoring network
========================================================================
AHN, April 2019

Used by the heroku app leela-one-playout, which is a separate github repo.
It is connected to heroku. A push to the master branch will deploy there.

leela-one-playout (the GUI) is a git submodule of leela-server (this repo).

WARNING: You need the leela weights. Get them with
$ cd leela-server
$ wget http://zero.sjeng.org/best-network

You also need the weights for our own networks. Get them with

$ cd leela-server/static/models
$ aws s3 cp s3://ahn-uploads/leela-server-models/nn_score.hd5 .
$ aws s3 cp s3://ahn-uploads/leela-server-models/nn_leelabot.hd5 .
 
To start the back end leela, use something like

gunicorn leela_server:app --bind 0.0.0.0:2718 -w 1

The GUI needs to know the port. Edit leela-one-playout/static/main.js .
You can switch between test and production at the very top.

The leela-one-playout GUI expects the back end at https://ahaux.com/leela_server .
The apache2 config on ahaux.com (marfa) forwards leela-server to port 2719:

$ cat /etc/apache2/sites-available/ahaux.conf 
<VirtualHost *:443>
    SSLEngine On
    SSLCertificateFile /etc/ssl/certs/ahaux.com.crt
    SSLCertificateKeyFile /etc/ssl/private/ahaux.com.key
    SSLCACertificateFile /etc/ssl/certs/ca-certificates.crt

    ServerAdmin admin@ahaux.com
    ServerName www.ahaux.com
    DocumentRoot /var/www/ahaux
    ErrorLog /var/www/ahaux/log/error.log
    CustomLog /var/www/ahaux/log/access.log combined

   <Proxy *>
        Order deny,allow
          Allow from all
    </Proxy>
    ProxyPreserveHost On
    <Location "/leela_server">
          ProxyPass "http://127.0.0.1:2719/"
          ProxyPassReverse "http://127.0.0.1:2719/"
    </Location>

</VirtualHost>

Point your browser at
https://leela-one-playout.herokuapp.com

Deployment Process for leela-server
-------------------------------------
Log into the server (marfa), then:

$ cd /var/www/leela-server
$ systemctl stop leela-server
$ git pull origin master
$ git submodule update --init --recursive
$ systemctl start leela-server

The service configuration is in 

/etc/systemd/system/leela-server.service:

[Unit]
Description=leela-server
After=network.target

[Service]
User=ahauenst
Restart=on-failure
WorkingDirectory=/var/www/leela-server
ExecStart=/home/ahauenst/miniconda/envs/venv-dlgo/bin/gunicorn -c /var/www/leela-server/gunicorn.conf -b 0.0.0.0:2719 -w 1 leela_server:app

[Install]
WantedBy=multi-user.target

Enable the service with

$ sudo systemctl daemon-reload
$ sudo systemctl enable leela-server

Deployment Process for leela-one-playout (the Web front end)
--------------------------------------------------------------

The heroku push happens through github.
Log into the server (marfa), then:

$ cd /var/www/leela-server/leela-one-playout
$ git pull origin dev
$ git pull origin master
<< Change the server address to prod in static/main.js >>
$ git merge dev
$ git push origin master

Log out of the server.
On your desktop, do

$ heroku logs -t --app leela-one-playout

to see if things are OK. 

Point your browser at
https://leela-one-playout.herokuapp.com


=== The End ===

