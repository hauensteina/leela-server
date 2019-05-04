
A back end API to ask leela for moves and run a keras scoring network
========================================================================
AHN, April 2019

Used by the heroku app leela-one-playout, which is a separate github repo.
It is connected to heroku. A push to the master branch will deploy there.

leela-one-playout (the GUI) is a git submodule of leela-server (this repo).

WARNING: You need the weights. Do
$ wget http://zero.sjeng.org best-network
 
To start the back end leela, use

gunicorn leela_server:app --bind 0.0.0.0:2719 -w 1

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


=== The End ===

