#!/usr/bin/env python

"""
Usage:
    tracker.py list
    tracker.py start <task> [<starttime>]
    tracker.py stop [<endtime>]
    tracker.py rm <task>
    tracker.py details <task>
    tracker.py pop <task>
    tracker.py push <task> <starttime> <endtime>
"""

from docopt import docopt
import cPickle as pickle
from datetime import timedelta
from datetime import datetime
import os

class Task(object):
  def __init__(self, name):
    self.name = name
    self.times = []
  
  def start(self, starttime):
    if not self.is_active():
      self.times.append(Timeslice(starttime))
      print self.summary()
    else:
      print "ERROR: Current task is already active"
    
  def stop(self, endtime):
    if not self.is_active():
      print "ERROR: Current task isn't active (start it first)"
      return

    if self.times[-1].start > endtime:
      print "ERROR: endtime before starttime"
      print self.times[-1]
      return

    self.times[-1].stop(endtime)

    # TODO(jeeva): make this use some stats based on average delta size over task/all tasks etc.
    if self.times[-1].minutes() > 60:
      print "ALERT: Looks like you worked for %d:%d" % (self.times[-1].hours_and_minutes())
      print "       This is longer than an 1hr. Bit suss..."
      print "       Can be fixed by called stop with an end time"
      print self.times[-1]
    else:
      print self.times[-1]

  def is_active(self):
    return any([t.is_active() for t in self.times])

  def pop(self):
    print "popping...", self.times[-1]
    self.times = self.times[0:-1]

  def push(self, starttime, endtime):
    ts = Timeslice(starttime)
    ts.stop(endtime)
    self.times.append(ts)

  def minutes(self):
    return sum([t.minutes() for t in self.times])

  def hours_and_minutes(self):
    m = self.minutes()
    return (m / 60, m % 60)

  def summary(self):
    hours, minutes = self.hours_and_minutes()
    active_msg = ''
    if self.is_active():
      active_msg = "(in progress, started at: %s)" % fmt_datetime(self.times[-1].start)

    return "%30s:\t%.2d:%.2d %s" % (self.name, hours, minutes, active_msg)

  def details(self):
    return '\n'.join([str(t) for t in self.times])
      
class Timeslice(object):
  def __init__(self, starttime=None):
    self.start = starttime or datetime.now()
    self.end = None

  def is_active(self):
    return self.end is None

  def stop(self, endtime):
    self.end = endtime

  def minutes(self):
    #TODO(jeeva): bit suss. Never really want days
    return self.timedelta().days*24*60 + self.timedelta().seconds/60

  def hours_and_minutes(self):
    m = self.minutes()
    return (m / 60, m % 60)

  def timedelta(self):
    return self.end_or_now() - self.start

  def end_or_now(self):
    if self.is_active():
      return datetime.now()
    else:
      return self.end

  def __str__(self):
    if self.is_active():
      return "* %s\t%s\t%s" % (fmt_datetime(self.start), fmt_datetime(self.end_or_now()), self.minutes())
    else:
      return "  %s\t%s\t%s" % (fmt_datetime(self.start), fmt_datetime(self.end_or_now()), self.minutes())

class TaskManager(object):
  def __init__(self):
    self.tasks = {}

  def show(self):
    for t in self.tasks.values():
      print t.summary()

  def start(self, name, starttime):
    if name not in self.tasks:
      self.tasks[name] = Task(name)

    # If there already exists an active task, stop it first
    for t in self.tasks.values():
      if t.is_active():
        t.stop(self.parse_or_now(starttime))

    self.tasks[name].start(self.parse_or_now(starttime))

  def stop(self, endtime):
    for t in self.tasks.values():
      if t.is_active():
        t.stop(self.parse_or_now(endtime))

  def delete(self, name):
    del self.tasks[name]

  def details(self, name):
    print self.tasks[name].summary()
    print self.tasks[name].details()

  def pop(self, name):
    self.tasks[name].pop()
  
  def push(self, name, starttime, endtime):
    self.tasks[name].push(self.parse_or_now(starttime), self.parse_or_now(endtime))

  def parse_or_now(self, s):
    if s:
      d = datetime.strptime(s, "%Y-%m-%d %H:%M")
      if d > datetime.now():
        raise ValueError, "%s is in the future" % d
      return d
    else:
      return datetime.now()

def fmt_datetime(d):
  return d.strftime("%Y-%m-%d %H:%M")

if __name__ == '__main__':
  arguments = docopt(__doc__, version='0.0')
  tasks = TaskManager()
  if os.path.exists("tasks.pickle"):
    tasks = pickle.load(open("tasks.pickle"))

  if arguments['list']:
    tasks.show()
  elif arguments['start']:
    tasks.start(arguments['<task>'], arguments['<starttime>'])
  elif arguments['stop']:
    tasks.stop(arguments['<endtime>'])
  elif arguments['rm']:
    tasks.delete(arguments['<task>'])
  elif arguments['details']:
    tasks.details(arguments['<task>'])
  elif arguments['pop']:
    tasks.pop(arguments['<task>'])
  elif arguments['push']:
    tasks.push(arguments['<task>'], arguments['<starttime>'], arguments['<endtime>'])

  pickle.dump(tasks, open("tasks.pickle", "w"))
