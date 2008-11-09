import sys, time, os
from datetime import date
import string


#This class represent a task in GTG.
class Task :
    def __init__(self, ze_id) :
        #the id of this task in the project
        #tid is a string ! (we have to choose a type and stick to it)
        self.tid = str(ze_id)
        self.content = "Press Escape or close this task to save it"
        self.sync_func = None
        self.title = "My new task"
        #available status are : Active - Done - Dismiss
        self.status = "Active"
        self.done_date = None
        self.due_date = None
        self.start_date = None
                
    def get_id(self) :
        return self.tid
        
    def get_title(self) :
        return self.title
    
    def set_title(self,title) :
        self.title = title
        
    def set_status(self,status) :
        self.status = status
        
    def get_status(self) :
        return self.status
        
    #function to convert a string of the form XXXX-XX-XX
    #to a date (where X are integer)
    def __strtodate(self,stri) :
        tabu = stri.split('-')
        return date(int(tabu[0]),int(tabu[1]),int(tabu[2]))
        
    def set_due_date(self,fulldate) :
        self.due_date = self.__strtodate(fulldate)
        
    def get_due_date(self) :
        return str(self.due_date)
    
    def get_days_left(self) :
        difference = self.due_date - date.today()
        return difference.days
        
    def get_text(self) :
        #defensive programmtion to avoid returning None
        if self.content :
            return str(self.content)
        else :
            return ""
        
    def set_text(self,texte) :
        self.content = str(texte)
        
    #This is a callback. The "sync" function has to be set
    def set_sync_func(self,sync) :
        self.sync_func = sync
        
    def sync(self) :
        if self.sync_func :
            self.sync_func(self.tid)
        
###########################################################################
        
#This class represent a project : a list of tasks sharing the same backend
class Project :
    def __init__(self, name) :
        self.name = name
        self.list = {}
        self.sync_func = None
        
    def list_tasks(self):
        result = self.list.keys()
        #we must ensure that we not return a None
        if not result :
            result = []
        return result
        
    def active_tasks(self) :
        return self.__list_by_status(["Active"])
        
    def unactive_tasks(self) :
        return self.__list_by_status(["Done","Dismissed"])
    
    def __list_by_status(self,status) :
        result = []
        for st in status :
            for tid in self.list.keys() :
                if self.get_task(tid).get_status() == st :
                    result.append(tid)
        return result
            
        
    def get_task(self,ze_id) :
        return self.list[str(ze_id)]
        
    def add_task(self,task) :
        tid = task.get_id()
        self.list[str(tid)] = task
        
    def new_task(self) :
        tid = self.__free_tid()
        task = Task(tid)
        self.list[str(tid)] = task
        return task
    
    def delete_task(self,tid) :
        del self.list[tid]
        self.sync()
    
    def __free_tid(self) :
        k = 0
        while self.list.has_key(str(k)) :
            k += 1
        return str(k)
        
    #This is a callback. The "sync" function has to be set
    def set_sync_func(self,sync) :
        self.sync_func = sync
        
    def sync(self) :
        self.sync_func()
        
        
    
