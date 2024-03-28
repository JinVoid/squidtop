#!/usr/bin/python3

import os
import sys
import time
_now = time.time
import curses
import argparse

GiMiKify         = True # show plain numbers or units (Kibi/Kilo...)
SCREEN           = None
LOG              = None
INTERVAL         = 2 # refresh rate in seconds
INTERVAL_MIN     = 0.1 # main loop sleep; affects user input responsiveness
TOP_NUM          = 100 # toplist default size; adapts to screen
MODE             = 0
MODE_STR         = ("Bytes/User", "Requests/User", "Bytes/Site", "Requests/Site")
MODE_SWITCH      = False
START_TIME       = _now()
NEXT_TIME        = START_TIME + INTERVAL
SQUID_STATS      = (0, 0, 0, 0)
REQ_TOTAL        = 0
REQ_RECENT       = 0
REQ_BYTES_TOTAL  = 0
REQ_BYTES_RECENT = 0
REQ_TIME         = START_TIME # an interval for averages
USERS            = set()
REQ_SITE         = dict()
REQ_USER         = dict()
BYTES_SITE       = dict()
BYTES_USER       = dict()
TOP_REQ_SITE     = list()
TOP_REQ_USER     = list()
TOP_BYTES_SITE   = list()
TOP_BYTES_USER   = list()

def init_curses():
  global SCREEN, TOP_NUM
  SCREEN = curses.initscr()
  curses.noecho(); curses.cbreak(); curses.curs_set(0)
  SCREEN.keypad(True); SCREEN.nodelay(True)
  TOP_NUM = SCREEN.getmaxyx()[0] - 1

def _exit(status, message):
  if SCREEN:
    curses.echo(); curses.nocbreak(); curses.curs_set(1)
    SCREEN.keypad(False); curses.endwin()
  if LOG:
    LOG.close()
  print(message)
  try:
    sys.exit(status)
  except SystemExit:
    os._exit(status)

def gimikify(n, units=1024):
  suffix = 'KMGTPEZY'
  d = units; j = 0
  while d < n:
    if (n / d) < units:
      break
    d *= units; j += 1
  if n > (units - 1):
    return "%.2f" % (n / d) + suffix[j]
  else:
    return str(n)

def time_conv(s):
  h = s // 3600; s -= h * 3600; h = str(h).zfill(2)
  m = s // 60; s -= m * 60; m = str(m).zfill(2)
  return "%s:%s:%s" % (h, m, str(s).zfill(2))

def parse_socket(s):
  addr, port = s.split(':')
  port = int(port, 10)
  if port < 1 or port > 65535:
    return None
  port = hex(port)[2:].upper().zfill(4)
  addr = addr.split('.')
  if len(addr) != 4:
    return None
  for i, n in enumerate(addr):
    n = int(n, 10)
    if n < 0 or n > 255:
      return None
    addr[i] = hex(n)[2:].upper().zfill(2)
  if sys.byteorder == 'little':
    addr.reverse()
  addr = ''.join(addr)
  return addr + ':' + port

def draw_screen(t):
  global REQ_RECENT, REQ_BYTES_RECENT, REQ_TIME, TOP_NUM
  ratings = (BYTES_USER, REQ_USER, BYTES_SITE, REQ_SITE)[MODE]
  toplist = (TOP_BYTES_USER, TOP_REQ_USER, TOP_BYTES_SITE, TOP_REQ_SITE)[MODE]
  units = 1000 if MODE & 1 else 1024
  Y, X = SCREEN.getmaxyx(); TOP_NUM = Y - 1
  SCREEN.clear()
  if Y > 0:
    s = "Users(Act/Tot): %i/%i, Conn(Estab/Tot): %i/%i" % SQUID_STATS
    SCREEN.addnstr(0, 0, s, X)
  if Y > 1:
    s = "Requests(Last,Avg,Tot): %.2f/s, %.2f/s, %i" % (
      REQ_RECENT / (t - REQ_TIME), REQ_TOTAL / (t - START_TIME), REQ_TOTAL)
    SCREEN.addnstr(1, 0, s, X)
  if Y > 2:
    last = REQ_BYTES_RECENT / (t - REQ_TIME)
    last = gimikify(last) if GiMiKify else str(last)
    avg = REQ_BYTES_TOTAL / (t - START_TIME)
    avg = gimikify(avg) if GiMiKify else str(avg)
    tot = gimikify(REQ_BYTES_TOTAL) if GiMiKify else str(REQ_BYTES_TOTAL)
    s = "Bytes(Last,Avg,Tot): %s, %s, %s; Top: %i" % (
      last, avg, tot, len(toplist))
    SCREEN.addnstr(2, 0, s, X)
  REQ_RECENT = 0; REQ_BYTES_RECENT = 0; REQ_TIME = t
  if Y > 3:
    s = "Mode: " + MODE_STR[MODE] + ", Interval: " + str(INTERVAL) +\
      "s, Time elapsed: %s" % time_conv(int(t - START_TIME))
    SCREEN.addnstr(3, 0, s, X)
  if len(toplist):
    j = len(str(toplist[0][1])) if not GiMiKify else len(gimikify(toplist[0][1], units))
    j = 10 if GiMiKify and j < 10 else j
    for i in range(0, Y-4):
      if i > len(toplist):
        break
      item, value = toplist[i]
      value = gimikify(value, units) if GiMiKify else str(value)
      SCREEN.addnstr(i+4, 0, value.rjust(j) + "  " + item, X)
  SCREEN.refresh()

def update_ratings(requests):
  global REQ_TOTAL, REQ_RECENT, REQ_BYTES_TOTAL, REQ_BYTES_RECENT
  REQ_TOTAL += len(requests); REQ_RECENT += len(requests)
  for user, size, site in requests:
    REQ_BYTES_TOTAL += size; REQ_BYTES_RECENT += size
    for ratings, toplist, item, num in (
      (REQ_USER, TOP_REQ_USER, user, 1),
      (REQ_SITE, TOP_REQ_SITE, site, 1),
      (BYTES_USER, TOP_BYTES_USER, user, size),
      (BYTES_SITE, TOP_BYTES_SITE, site, size)):
      value = ratings.get(item, 0)
      value += num
      ratings[item] = value
      if len(toplist) < TOP_NUM:
        add_item = True; i = 0
        while i < len(toplist):
          if value >= toplist[i][1]:
            add_item = False
            toplist.insert(i, (item, value))
            if i < len(toplist)-1:
              j = i+1
              while j < len(toplist):
                if toplist[j][0] == item:
                  _ = toplist.pop(j); break
                j += 1
            break
          i += 1
        if add_item:
          toplist.append((item, value))
      elif value > toplist[-1][1]:
        i = 0
        while i < len(toplist):
          if value >= toplist[i][1]:
            toplist.insert(i, (item, value))
            if i < len(toplist)-1:
              j = i+1
              while j < len(toplist):
                if toplist[j][0] == item:
                  _ = toplist.pop(j); break
                j += 1
            if len(toplist) > TOP_NUM:
              _ = toplist.pop()
            break
          i += 1

def get_squid_stats():
  users = set(); conn = 0; estab = 0
  with open("/proc/net/tcp") as f:
    for l in f.readlines():
      l = l.split()
      if l[1] == "7701010A:0C38":
        conn += 1
        if l[3] == "01":
          estab += 1
        users.add(l[2].split(":")[0])
  USERS.update(users)
  return (len(users), len(USERS), estab, conn)

def read_log():
  line = LOG.readline()
  requests = list()
  while line:
    l = line.split()
    user = l[LOG_IDX_USER]
    size = int(l[LOG_IDX_SIZE], 10)
    site = l[LOG_IDX_SITE]
    if user and site:
      requests.append((user, size, site))
    line = LOG.readline()
  return requests

def check_log():
  l = LOG.readline().split()
  if not len(l):
    print("Empty log, cannot check format.")
    return False
  if len(l) <= max(LOG_IDX_USER, LOG_IDX_SIZE, LOG_IDX_SITE):
    print("Unknow log format, set indexes properly.")
    return False
  try:
    user = l[LOG_IDX_USER]
    size = int(l[LOG_IDX_SIZE], 10)
    site = l[LOG_IDX_SITE]
  except ValueError:
    print("Wrong index for bytes field in the log")
    return False
  if user and site:
    return True
  return False

def get_args():
  global LOG_IDX_USER, LOG_IDX_SIZE, LOG_IDX_SITE
  argparser = argparse.ArgumentParser(description='A tool for monitoring squid '
    "server's top users and the sites they use.")
  argparser.add_argument('-f', '--file', dest='logfile', nargs='?', help="squid"
    "'s access log file (/var/log/squid/access.log is the default).",
    default="/var/log/squid/access.log")
  argparser.add_argument('-u', '--user', dest='user', nargs='?', type=int,
    help="user field index in a log string (that field contains the client "
    "address). For the default format of access log this is 2.", default=2)
  argparser.add_argument('-s', '--size', dest='size', nargs='?', type=int,
    help="size field index in a log string (that field contains the amount of "
    "data in bytes delivered to the client). For the default format of access "
    "log this is 4.", default=4)
  argparser.add_argument('-l', '--link', dest='link', nargs='?', type=int,
    help="URL field index in a log string (that field contains the URL). For "
    "the default format of access log this is 6.", default=6)
  args = argparser.parse_args()
  if args.user != args.size != args.link:
    LOG_IDX_USER = args.user; LOG_IDX_SIZE = args.size; LOG_IDX_SITE = args.link
  else:
    print("Error! Field indices must not match."); sys.exit(1)
  return args

if __name__ == '__main__':
  try:
    args = get_args()
    LOG = open(args.logfile, 'r')
    if not check_log():
      sys.exit(1)
    LOG.seek(0,2) # seek to EOF
    init_curses()
    while True:
      t = _now()
      update_ratings(read_log())
      key = SCREEN.getch()
      if key != -1:
        if chr(key) in 'QqXx':
          _exit(0, "\n")
        elif chr(key) in 'Ii':
          GiMiKify = not GiMiKify
        elif chr(key) in '0123456789':
          k = key - 48
          INTERVAL = 10 if k == 0 else k
          if (t - REQ_TIME) >= INTERVAL:
            NEXT_TIME = t
        elif chr(key) in 'Mm':
          MODE = (MODE + 1) & 3; MODE_SWITCH = True
        elif chr(key) in 'SsUu':
          MODE ^= 2; MODE_SWITCH = True
        elif chr(key) in 'BbRr':
          MODE ^= 1; MODE_SWITCH = True
      if MODE_SWITCH:
        MODE_SWITCH = False
        draw_screen(t)
        NEXT_TIME += INTERVAL
        continue
      if t >= NEXT_TIME:
        #if t > (NEXT_TIME + 2 * INTERVAL): # lagged too much
        #  NEXT_TIME = t # so we don't strain the system any more
        NEXT_TIME += INTERVAL
        SQUID_STATS = get_squid_stats()
        draw_screen(t)
      else:
        time.sleep(INTERVAL_MIN)
  except KeyboardInterrupt:
    _exit(0, "\n")
  except Exception as E:
    _exit(1, E)

# TODO
# cmdline args!!!
# worker thread?
# per-user top sites by requests/bytes
# per-site top users by bytes
