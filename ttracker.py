#!/usr/bin/env python

"""
A command line tool to track time against tasks in freshbooks. 

The tool is meant to be used offline - it only syncs with freshbooks when 
you explicitly tell it too via the sync command.

Usage:
    ttracker.py list
    ttracker.py delete <task>
    ttracker.py details <task>
    ttracker.py start <task> <project-id> [<starttime> <notes>]
    ttracker.py stop [--notes=<notes> <endtime> <notes>]
    ttracker.py pop <task>
    ttracker.py push <task> <project-id> <starttime> <endtime> [<notes>]
    ttracker.py config [<username> <apikey>]
    ttracker.py projects [--display-from-cache]
    ttracker.py sync

list: 
  Display all active tasks, along with a short summary
delete: 
  Delete the given task. All time logged remains - the task just disappears from this tool. This action can be undone in freshbooks
details:
  List all time logged for a given task
start: 
  Start logging time to a given task/project
stop: 
  stop logging time to whichever task is currently active
pop: 
  A helper to manage logging errors. Remove the last logged entry for a given task, and display it
push: 
  A helper to manager logging errors, Push a new time log entry for a given task
config: 
  Configure your freshbooks username and API key
projects:
  List all projects you can log time to. This is grabbed live from freshbooks unless the --display-from-cache option is enabled
sync:
  The only action that modifies freshbooks - this updates freshbooks with all logged time
"""

from docopt import docopt
from datetime import timedelta
from datetime import datetime
import os
import refreshbooks.api
import sys
import tempfile
import jsonpickle
import json
import math

class Project(object):
  def __init__(self, id, name):
    self.id = id
    self.name = name

class Task(object):
  def __init__(self, name, entries=None, deleted_entries=None, freshbooks_id=None):
    self.name = name
    self.entries = entries or []
    self.deleted_entries = deleted_entries or []
    self.freshbooks_id = freshbooks_id
  
  def start(self, project, starttime, notes=''):
    if not self.is_active():
      self.entries.append(Entry(project, starttime, notes=notes))
      print self.summary()
    else:
      print "ERROR: Current task is already active"
    
  def stop(self, endtime, max_entry_warning, notes=''):
    if not self.is_active():
      print "ERROR: Current task isn't active (start it first)"
      return

    if self.entries[-1].start > endtime:
      print "ERROR: endtime before starttime"
      print self.entries[-1]
      return

    self.entries[-1].stop(endtime, notes)

    if self.entries[-1].minutes() > max_entry_warning:
      print "WARNING: Looks like you worked for %d:%d" % (self.entries[-1].hours_and_minutes())
      print "       Is this an error? Can be fixed with 'pop'."
    print self.name, ':', self.entries[-1]

  def is_active(self):
    return any([t.is_active() for t in self.entries])

  def pop(self):
    print "popping...", self.entries[-1]
    self.deleted_entries.append(self.entries[-1])
    self.entries = self.entries[0:-1]

  def push(self, project, starttime, endtime, notes):
    ts = Entry(project, starttime, endtime, notes=notes)
    ts.stop(endtime)
    self.entries.append(ts)

  def minutes(self):
    return sum([t.minutes() for t in self.entries])

  def hours_and_minutes(self):
    m = self.minutes()
    return (m / 60, m % 60)

  def summary(self, field_size=None):
    hours, minutes = self.hours_and_minutes()
    active_msg = ''
    if self.is_active():
      active_msg = "(in progress, started at: %s)" % fmt_datetime(self.entries[-1].start)

    if field_size is None: field_size = len(self.name)
    name_field = ('%%%ds' % field_size) % self.name
    return "%s:\t%.2d:%.2d %s" % (name_field, hours, minutes, active_msg)

  def details(self):
    return '\n'.join([str(t) for t in self.entries])

  def toJSON(self):
    return {
        'name': self.name,
        'entries': self.entries,
        'deleted_entries': self.deleted_entries,
        'freshbooks_id': self.freshbooks_id,
    }

  def pretty_name(self):
    return self.name.replace('_', ' ')
     
class Entry(object):
  def __init__(self, project, starttime, endtime=None, notes='', freshbooks_id=None):
    self.project = project
    self.start = starttime or datetime.now()
    self.notes = notes
    self.end = endtime
    self.freshbooks_id = freshbooks_id

  def is_active(self):
    return self.end is None

  def stop(self, endtime, notes=''):
    self.end = endtime
    self.notes += notes

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
    if self.notes:
      notes = '(%s: %s)' % (self.project.name, self.notes)
    else:
      notes = '(%s)' % self.project.name

    if self.is_active():
      start = '* '
    else:
      start = '  '

    return "%s %s - %s\t%s\t%s" % (start, fmt_datetime(self.start), fmt_datetime(self.end_or_now()), self.minutes(), notes)

  def toJSON(self):
    if self.end is not None:
      end = fmt_datetime(self.end)
    else:
      end = None

    return {
        'project_id': self.project.id,
        'start': fmt_datetime(self.start),
        'end': end,
        'notes': self.notes,
        'freshbooks_id': self.freshbooks_id
    }

class TaskManager(object):
  def __init__(self, db_file):
    self.db_file = db_file
    self.tasks = {}
    self.deleted_tasks = {}
    self.projects = {}
    self.username = ''
    self.apikey = ''

  def load(self):
    if os.path.exists(self.db_file):
      obj = json.loads(open(self.db_file).read())
      self.projects = obj.get('projects', {})
      self.tasks = self.decode_tasks(obj.get('tasks', {}))
      self.deleted_tasks = self.decode_tasks(obj.get('deleted_tasks', {}))
      self.username = obj.get('username', '')
      self.apikey = obj.get('apikey', '')

  def decode_tasks(self, json_obj):
    tasks = {}
    for k,v in json_obj.items():
      tasks[k] = Task(v['name'],
                      self.decode_entries(v['entries']),
                      self.decode_entries(v['deleted_entries']),
                      v['freshbooks_id'])
    return tasks

  def decode_entries(self, json_obj):
    entries = []
    for e in json_obj:
      entries.append(Entry(
                      self.mk_project(e['project_id']),
                      try_parse_date(e['start']),
                      try_parse_date(e['end'] or ''),
                      e['notes'],
                      e['freshbooks_id'],
                    ))
    return entries

  def mk_project(self, pid):
    return Project(pid, self.projects[pid])

  def save(self):
    fd,tmpfile = tempfile.mkstemp()
    f = os.fdopen(fd, 'w')
    f.write(json.dumps(
              {'tasks': self.tasks,
               'deleted_tasks': self.deleted_tasks,
               'projects': self.projects,
               'username': self.username,
               'apikey': self.apikey},
              cls=JSONEncoder))
    f.close()
    os.rename(tmpfile, self.db_file)

  def config(self, username=None, apikey=None):
    self.username = username or prompt("Freshbooks Username: ")
    self.apikey = apikey or prompt("Freshbooks Api Key: ")

  def create_freshbooks_client(self):
    return refreshbooks.api.TokenClient('%s.freshbooks.com' % self.username, self.apikey)
  
  def get_project_from_freshbooks(self):
    c = self.create_freshbooks_client()
    resp = c.project.list(per_page=5000)
    for p in resp.projects.project:
      self.projects[str(p.project_id)] = str(p.name)

  def display_projects(self):
    for pid,name in self.projects.items():
      print pid, name
    
  def list(self):
    ts = self.tasks.values()
    ts.sort(key=lambda t: t.name)
    if ts:
      field_size = max([len(t.name) for t in ts])
      for t in ts:
        print t.summary(field_size)
    else:
        print "No tasks, start logging time with the 'ttracker.py start' command"

  def start(self, name, project_id, starttime, notes):
    if name not in self.tasks:
      self.tasks[name] = Task(name)

    # Make sure the project is valid
    if project_id not in self.projects:
      print "Invalid project id - task not started. Valid projects are"
      self.display_projects()

    # If there already exists an active task, stop it first
    for t in self.tasks.values():
      if t.is_active():
        t.stop(parse_or_now(starttime))
    self.tasks[name].start(self.mk_project(project_id), parse_or_now(starttime), notes or '')

  def stop(self, endtime, notes):
    all_logged_time = []
    for t in self.tasks.values():
      for e in t.entries:
        if e.is_active():
          all_logged_time.append(e.minutes())

    # Use stats if we have more than some threshold of entries, otherwise
    # just hard-code our warning value
    if len(all_logged_time) > 10:
      avg = sum(all_logged_time) / len(all_logged_time)
      stddev = math.sqrt(sum([(m - avg)**2 for m in all_logged_time])/len(all_logged_time))
      max_entry_warning = avg + 2*stddev
    else:
      max_entry_warning = 60

    for t in self.tasks.values():
      if t.is_active():
        t.stop(parse_or_now(endtime), max_entry_warning, notes or '')
        return
    print "No active task"

  def delete(self, name):
    if self.tasks[name].is_active():
      print "Can't delete an active task. Stop it first"
      return

    self.deleted_tasks[name] = self.tasks[name]
    del self.tasks[name]

  def details(self, name):
    print self.tasks[name].summary()
    print self.tasks[name].details()

  def pop(self, name):
    self.tasks[name].pop()
  
  def push(self, name, project_id, starttime, endtime, notes):
    self.tasks[name].push(self.mk_project(project_id), parse_or_now(starttime), parse_or_now(endtime), notes or '')

  def all_tasks(self):
    for t in self.tasks.values(): yield t
    for t in self.deleted_tasks.values(): yield t

  def sync(self):
    c = self.create_freshbooks_client()

    print "Creating tasks..."
    for t in self.all_tasks():
      if t.freshbooks_id is None:
        print "    %r" % t.pretty_name()
        r = c.task.create(task={'name': t.pretty_name()})
        t.freshbooks_id = str(r.task_id)
        self.save()

    print "Updating task project link..."
    # get all projects - we need this to update their task lists
    project_tasks = {}
    mk_task = refreshbooks.api.types.task
    for p in c.project.list(per_page=5000).projects.project:
      if p.tasks.countchildren():
        project_tasks[str(p.project_id)] = [mk_task(task_id=t.task_id, rate=t.rate) for t in p.tasks.task]
      else:
        project_tasks[str(p.project_id)] = []

    for t in self.all_tasks():
      for e in t.entries:
        project_tasks[e.project.id].append(mk_task(task_id=t.freshbooks_id))

    for pid,tasks in project_tasks.items():
      c.project.update(project={
          'project_id': pid,
          'tasks': tasks,
          })

    # Create all new entries
    for t in self.all_tasks():
      print "Updating entries for '%s'..." % t.pretty_name()
      for e in t.entries:
        if not e.freshbooks_id:
          print "   Syncing: %s" % e
          
          r = c.time_entry.create(time_entry={
                  'project_id': e.project.id,
                  'task_id': t.freshbooks_id,
                  'hours': e.minutes() / 60.0,
                  'notes': e.notes,
                  'date': fmt_date(e.start)})
          e.freshbooks_id = str(r.time_entry_id)
          self.save()

      # sync up deletes
      while t.deleted_entries:
        e = t.deleted_entries.pop()
        if e.freshbooks_id:
          print "Deleting: %s" % e
          c.time_entry.delete(time_entry_id=e.freshbooks_id)
          self.save()

    # Finally, Sync up all task deletes with freshbooks
    for k in self.deleted_tasks.keys():
      t = self.deleted_tasks.pop(k)
      c.task.delete(task_id=t.freshbooks_id)
      self.save()

class JSONEncoder(json.JSONEncoder):
  def default(self, obj):
    if hasattr(obj, 'toJSON'):
      return obj.toJSON()
    else:
      return json.JSONEncoder.default(self, obj)

def parse_or_now(s):
  if s:
    d = try_parse_date(s)
    if not d:
      d = try_parse_date(datetime.now().strftime("%Y-%m-%d ") + s)

    if not d:
      raise ValueError, "Failed to parse %s as a datetime" % s

    if d > datetime.now():
      raise ValueError, "%s is in the future" % d
    return d
  else:
    return datetime.now()

def try_parse_date(s, fmt="%Y-%m-%d %H:%M"):
  try:
    d = datetime.strptime(s, fmt)
    return d
  except ValueError:
    return None

def fmt_datetime(d):
  return d.strftime("%Y-%m-%d %H:%M")

def fmt_date(d):
  return d.strftime("%Y-%m-%d")

def prompt(msg):
  sys.stdout.write(msg),
  return sys.stdin.readline().strip()

if __name__ == '__main__':
  arguments = docopt(__doc__, version='0.0')

  ttracker_db = os.environ.get('TTRACKER_DB', os.path.join(os.environ['HOME'], '.ttracker'))
  tasks = TaskManager(ttracker_db)
  tasks.load()

  # Do setup actions, if they haven't been done yet.
  if not tasks.apikey or not tasks.username:
    print "First time using ttracker running setup..."
    tasks.config()

  if not tasks.projects:
    print "Downloading project info from freshbooks..."
    tasks.get_project_from_freshbooks()

    # If we still don't have projects, freshbooks needs to be setup first
    if not tasks.projects:
      print "No Projects in freshbooks. Please create some, or get your employer to add you to theirs so you can start billing time."
      raise SystemExit,1

  if arguments['list']:
    tasks.list()
  elif arguments['delete']:
    tasks.delete(arguments['<task>'])
  elif arguments['details']:
    tasks.details(arguments['<task>'])
  elif arguments['start']:
    tasks.start(arguments['<task>'], arguments['<project-id>'], arguments['<starttime>'], arguments['<notes>'])
  elif arguments['stop']:
    tasks.stop(arguments['<endtime>'], arguments['<notes>'] or arguments['--notes'])
  elif arguments['pop']:
    tasks.pop(arguments['<task>'])
  elif arguments['push']:
    tasks.push(arguments['<task>'], arguments['<project-id>'], arguments['<starttime>'], arguments['<endtime>'], arguments['<notes>'])
  elif arguments['config']:
    tasks.config(arguments['[<username>]'], arguments['[<password>]'])
  elif arguments['projects']:
    if not arguments['--display-from-cache']:
      print "Downloading project info from freshbooks... (use '--display-from-cache' to work offline)"
      tasks.get_project_from_freshbooks()
    tasks.display_projects()
  elif arguments['sync']:
    tasks.sync()

  tasks.save()
