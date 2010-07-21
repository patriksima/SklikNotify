#!/usr/bin/python
# -*- coding: utf-8 -*-

__author__ = 'Patrik Šíma'
__version__ = '0.3'
__license__ = 'MIT'

import os
import re
import time
import string
import cookielib
import httplib
import urllib
import urllib2
import urlparse

from exceptions import Exception
from BeautifulSoup import BeautifulSoup


class SklikException(Exception):

    pass


class SklikConfig:

    username = ''
    password = ''
    url = {
        'login': 'https://login.szn.cz/loginProcess',
        'logout': 'https://www.sklik.cz/logout',
        'overview': 'https://www.sklik.cz/prehled-uctu',
        'keywordsave': 'https://www.sklik.cz/keywordSaveProcess'
        }
    agent = 'Mozilla/5.0 (X11; U; Linux i686; cs-CZ; rv:1.9.0.5) Gecko/2008121621 Ubuntu/8.04 (hardy) Firefox/3.0.5'
    autoactive = 'yes'
    email = {'to': '', 'from': ''}


class Sklik:

    def __init__(self):
        self.credit = 0.0

        self.tree = {}
        self.groups = {}
        self.keywords = {}
        self.campaigns = {}

        self.handlers = [urllib2.HTTPCookieProcessor(), urllib2.HTTPRedirectHandler()]
        self.connection = urllib2.build_opener(*self.handlers)
        urllib2.install_opener(self.connection)

    def request(self, url, params=None):
        try:
            if params is None:
                f = self.connection.open(url)
            else:
                f = self.connection.open(url, urllib.urlencode(params))
        except urllib2.HTTPError, e:
            raise SklikException, 'Chyba: %s' % e.code
        except urllib2.URLError, e:
            raise SklikException, 'Chyba: %s' % e.reason
        else:
            html = f.read()
            f.close()
            return html

    def login(self):
        """
        Prihlaseni k uctu
        """

        params = {
            'username': SklikConfig.username,
            'password': SklikConfig.password,
            'domain': 'seznam.cz',
            'login': "Přihlásit se",
            'serviceId': 'sklik',
            'disableSSL': '0',
            'forceSSL': '0',
            'lang': 'cz',
            'loginType': 'seznam',
            'returnURL': SklikConfig.url['overview'],
            'forceRelogin': '0',
            'coid': ''
            }

        html = self.request(SklikConfig.url['login'], params)

        s = html.find('http')
        e = html.find('>', s + 1)
        r = html[s:e - 1]
        o = urlparse.urlparse(r)
        d = dict([s.split('=') for s in o.query.split('&amp;')])

        self.request('http://' + o.netloc + o.path + '?' + o.query.replace('&amp;', '&'))

    def logout(self):
        """
        Odhlaseni z uctu
        """

        self.request(SklikConfig.url['logout'])

    def get_credit(self, html):
        """
        Vrati stav kreditu
        """

        soup = BeautifulSoup(html)
        p = soup.find('p', {'class': 'credit'})
        credit = re.findall(r"([0-9]+,[0-9]+)&nbsp;Kč", str(p))
        return float(credit[0].replace(',', '.'))

    def get_gcpc(self, html):
        """
        Vrati CPC sestavy
        """

        soup = BeautifulSoup(html)
        div = soup.find('div', {'class': 'detail group-setting'})
        cpc = re.findall(r"([0-9]+,[0-9]+)&nbsp;Kč", str(div))
        return float(cpc[1].replace(',', '.'))

    def check(self):
        """
        Zkontroluje sestavu na neaktivni slova
        """

        html = self.request(SklikConfig.url['overview'])

        self.credit = self.get_credit(html)

        soup = BeautifulSoup(html)
        camp = soup.find('div', {'class': 'overview-list'})

        if camp is None:
            raise SklikException, "V přehledu účtu není žádná kampaň."
        if camp.find('span'):
            return True
        return False

    def activate(self, url, groupid, keyid, cpc):
        """
        Aktivuje klicove slovo
        """

        params = {
            'list.0.url': '',
            'list.0.cpc': cpc,
            'list.0.id': keyid,
            'groupId': groupid
            }
        html = self.request(SklikConfig.url['keywordsave'], params)

    def activate_all(self):
        """
        Aktivace vsech neaktivnich klicovych slov
        """

        for (kid, v) in self.keywords.iteritems():
            url = v[1]
            print url
            matches = re.search(r"groupId=([0-9]+)", str(url))
            groupid = matches.group(1)
            matches = re.search(r"id=([0-9]+)", str(url))
            keyid = matches.group(1)
            matches = re.search(r"cpc=([0-9]+\.[0-9]+)", str(url))
            cpc = matches.group(1)
            self.activate(url, groupid, keyid, float(cpc))

    def load_overview(self):
        """
        Nacteni struktury uctu
        """

        html = self.request(SklikConfig.url['overview'])

        soup = BeautifulSoup(html)
        camp = soup.find('div', {'class': 'overview-list'})
        if camp is None:
            raise SklikException, 'V prehledu uctu neni zadna kampan.'

        for h3 in camp.findAll('h3'):
            if h3.find('span'):
                matches = re.search(r"campaignId=([0-9]+)", str(h3))
                campid = matches.group(1)
                self.tree[campid] = {}
                self.campaigns[campid] = h3.a.string.strip()
                for li in h3.nextSibling.nextSibling.findAll('li'):
                    if li.find('span'):
                        matches = re.search(r"groupId=([0-9]+)", str(li))
                        groupid = matches.group(1)
                        self.groups[groupid] = li.a.string.strip()
                        self.tree[campid][groupid] = []
                        self.load_keywords(campid, li.a['href'])

    def load_keywords(self, campid, url):
        """
        Nacteni neaktivnich klic. slov ze sestavy
        """

        matches = re.search(r"groupId=([0-9]+)", str(url))
        groupid = matches.group(1)

        html = self.request('http://www.sklik.cz' + url +  '&paging.count=500')
        soup = BeautifulSoup(html, convertEntities='html')
        gcpc = self.get_gcpc(html)
        table = soup.find('table', {'id': 'keyword-table'})
        if table is None:
            raise SklikException, 'Sestava neobsahuje klicova slova.'
        for tr in table.findAll('tr'):
            span = tr.find('span', {'class': re.compile('noactive')})
            if span:
                td = tr.find('td', {'class': 'tName'})
                kw = td.div.string.strip()
                if span.find('a'):
                    url = span.a['href']
                    matches = re.search(r"id=([0-9]+)", str(url))
                    keyid = matches.group(1)
                    matches = re.search(r"cpc=([0-9]+\.[0-9]+)", str(url))
                    cpc = matches.group(1)
                    self.tree[campid][groupid].append((kw, url, cpc))
                    self.keywords[keyid] = (kw, url, cpc)
                else:
                    self.tree[campid][groupid].append((kw, None, None))


if __name__ == '__main__':
    print 'Sklik Notify v.%s' % __version__
    print '=================='
    sklik = Sklik()
    print "Přihlášení...",
    sklik.login()
    print 'OK'
    print "Kontrola neaktivních slov...",
    res = sklik.check()
    print 'OK'
    if res:
        if sklik.credit == 0.0:
            print u"\tNa účtu je nulový kredit, takže se vaše inzeráty nezobrazují!"
        print u"Načítám přehled účtu...",
        sklik.load_overview()
        print 'OK'
        for (k, v) in sklik.tree.iteritems():
            print u"Kampaň %s" % sklik.campaigns[k]
            for (j, k) in v.iteritems():
                print u'\tSestava %s' % sklik.groups[j]
                for m in k:
                    if m[1] is None:
                        print u'\t\tKW: %s, nelze aktivovat' % m[0]
                    else:
                        print u'\t\tKW: %s, CPC: %s' % (m[0], m[2])
        input = raw_input('Aktivovat slova? (Ano/Ne): ')
        input = input.lower()
        if input == 'a' or input == 'ano':
            print 'Aktivuji...',
            sklik.activate_all()
            print 'OK'
    print "Odhlášení...",
    sklik.logout()
    print 'OK'
