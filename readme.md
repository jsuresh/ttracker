= TTracker.py =
A command line tool to track time against tasks in freshbooks. 

The tool is meant to be used offline - it only syncs with freshbooks when 
you explicitly tell it too via the sync command.

==Setup==
 1. Install libraries in requirements.txt
 2. run ttracker.py init

==Examples==
Have this running in a terminal window to give you a summary of all active tasks:

    $ watch ttracker.py list

Start logging time to a task and a given project. If the task doesn't exist, itwill be created for you.

    ttracker.py start learn_ttracker 1

To Switch the task you are working on, simply start logging time to a different task. It will automatically switch tasks

    ttracker.py start actually_do_some_work 1

When you are done for the day, sign off with the stop command

    ttracker.py stop

Sync entries with freshbooks

    ttracker.py sync

Start or stop a task with a specific time. Often useful if you've forgotten to start the timer. The date is assumed to be today if it's not specified.

    ttracker.py start "15:00"
    ttracker.py stop "16:00"

Delete and fixup the last entry. Useful if you just made a mistake :p

    ttracker.py pop last_task_I_worked_on
    ttracker.py push last_task_I_worked_on "15:00" "17:00"
