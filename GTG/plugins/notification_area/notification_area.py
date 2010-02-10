# -*- coding: utf-8 -*-
# Copyright (c) 2009 - Paulo Cabido <paulo.cabido@gmail.com>
#                    - Luca Invernizzi <invernizzi.l@gmail.com> 
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <http://www.gnu.org/licenses/>.

import gtk
import os
try:
    import appindicator
    indicator_capable = True
except:
    indicator_capable = False

from GTG.core.task import Task
from GTG import _



class NotificationArea:


    DEFAULT_PREFERENCES = {"start_minimized": False}
    PLUGIN_NAME = "notification_area"
    MAX_TITLE_LEN = 30
    
    def __init__(self):
        self.minimized = False
    
    def activate(self, plugin_api):
        self.plugin_api = plugin_api
        #Create the  menu
        self.create_static_menu()
        #initialize the right notification thing
        if indicator_capable:
            #Create an indicator icon
            self.ind = appindicator.Indicator ("gtg", \
                                  "indicator-messages", \
                                   appindicator.CATEGORY_APPLICATION_STATUS)
            self.ind.set_status (appindicator.STATUS_ACTIVE)
            self.ind.set_attention_icon ("indicator-messages-new")
            self.ind.set_icon("gtg")
            self.ind.set_menu(self.menu)
        else:
            data_dir = plugin_api.get_data_dir()
            icon = gtk.gdk.pixbuf_new_from_file_at_size(data_dir + \
                                "/icons/hicolor/16x16/apps/gtg.png", 16, 16)
            self.status_icon = gtk.status_icon_new_from_pixbuf(icon)
            self.status_icon.set_tooltip("Getting Things Gnome!")
            self.status_icon.connect('activate', self.minimize, plugin_api)
            self.status_icon.set_visible(True)
            self.status_icon.connect('popup-menu', \
                                     self.on_icon_popup, \
                                     self.menu)
        #Load the preferences
        self.preference_dialog_init()
        self.preferences_load()
        self.preferences_apply()
        #Connecting the signals about task changes
        requester = self.plugin_api.get_requester()
        requester.connect("task-added", self.on_task_added)
        requester.connect("task-deleted", self.on_task_deleted)
        requester.connect("task-modified", self.on_task_modified)
        #initial menu populate, just in case the plugin is not activated at GTG
        # startup time
        task_list = requester.get_active_tasks_list(workable = True )
        map(lambda t: self.add_menu_task(t), task_list)

    def deactivate(self, plugin_api):
        if indicator_capable:
            pass #####
        else:
            self.status_icon.set_visible(False)
        self.plugin_api.get_browser().start_minimized = False

## Helper methods ##############################################################

    def open_task(self, widget, tid = None):
        """Opens a task in the TaskEditor, if it's not currently opened"""
        browser = self.plugin_api.get_browser()
        if tid == None:
            tid = self.plugin_api.get_requester().new_task().get_id()
        if browser:
            browser.open_task(tid)
    
    def minimize(self, widget, plugin_api):
        if self.view_main_window_signal != None:
            self.view_main_window.disconnect(self.view_main_window_signal)
            self.view_main_window_signal = None
        if self.minimized:
            self.view_main_window.set_active(True)
            self.view_main_window.show()
            plugin_api.show_window()
            self.minimized = False
        else:
            self.view_main_window.set_active(False)
            self.view_main_window.show()
            plugin_api.hide_window()
            self.minimized = True
        self.view_main_window_signal = self.view_main_window.connect(\
                                'activate', self.minimize, self.plugin_api)

## Menu methods #################################################################

    def add_menu_task(self, tid):
        """Adds a task in the menu, trimming the title if necessary"""
        task = self.plugin_api.get_task(tid)
        if self.tasks_in_menu.has_key(tid):
            #task is already in the menu, updating the title
            menu_item = self.tasks_in_menu[tid]
            menu_item.get_children()[0].set_label(task.get_title())
            return
        #trimming of the title
        title = task.get_title()[0:self.MAX_TITLE_LEN]
        if len(title)== self.MAX_TITLE_LEN:
            title = title + "..."
        #putting a separator between the tasks and the static menu
        if self.task_separator == None:
            self.task_separator = gtk.SeparatorMenuItem()
            self.task_separator.show()
            self.menu.append(self.task_separator)
        #creating the menu item
        menu_item = gtk.ImageMenuItem(title)
        menu_item.connect('activate', self.open_task, tid)
        menu_item.show()
        self.menu.append(menu_item)
        self.tasks_in_menu[tid] = menu_item
    
    def remove_menu_task(self, tid):
        if not self.tasks_in_menu.has_key(tid):
            return
        menu_item = self.tasks_in_menu.pop(tid)
        self.menu.remove(menu_item)
        #if the dynamic menu is empty, remove the separator
        if len(self.tasks_in_menu.keys()) == 0:
            self.menu.remove(self.task_separator)
            self.task_separator = None

    def create_static_menu(self):
        #Tasks_in_menu will hold the menu_items in the menu
        self.tasks_in_menu = dict()
        self.task_separator = None  
        self.menu = gtk.Menu()
        #view in main window checkbox
        self.view_main_window = gtk.CheckMenuItem(_("_View Main Window"))
        self.view_main_window.set_active(not self.minimized)
        self.view_main_window_signal = self.view_main_window.connect(\
                                      'activate', \
                                      self.minimize,\
                                      self.plugin_api)
        self.menu.append(self.view_main_window)
        #add new task
        menuItem = gtk.ImageMenuItem(gtk.STOCK_ADD)
        menuItem.get_children()[0].set_label(_('Add _New Task'))
        menuItem.connect('activate', self.open_task)
        self.menu.append(menuItem)
        #realizing the menu
        self.menu.show_all()


## Callback methods ############################################################

    def on_icon_popup(self, icon, button, timestamp, menu=None):
        #appindicator handles menus transparently
        if not indicator_capable:
            menu.popup(None, None, gtk.status_icon_position_menu, \
                       button, timestamp, icon)

    def onTaskOpened(self, plugin_api):
        pass

    def on_task_added(self, requester, tid):
        self.add_menu_task(tid)

    def on_task_deleted(self, requester, tid):
        self.remove_menu_task(tid)

    def on_task_modified(self, requester, tid):
        task = requester.get_task(tid)
        status = task.get_status()
        if status == Task.STA_ACTIVE and task.is_workable():
            self.add_menu_task(tid)
        else:
            self.remove_menu_task(tid)

## Preferences methods #########################################################

    def is_configurable(self):
        """A configurable plugin should have this method and return True"""
        return True

    def configure_dialog(self, plugin_apis, manager_dialog):
        self.preferences_load()
        self.preferences_dialog.set_transient_for(manager_dialog)
        self.chbox_miminized.set_active(self.preferences["start_minimized"])
        self.preferences_dialog.show_all()

    def on_preferences_cancel(self, widget = None, data = None):
        self.preferences_dialog.hide()
        return True

    def on_preferences_ok(self, widget = None, data = None):
        self.preferences["start_minimized"] = self.chbox_miminized.get_active()
        self.preferences_apply()
        self.preferences_store()
        self.preferences_dialog.hide()

    def preferences_load(self):
        data = self.plugin_api.load_configuration_object(self.PLUGIN_NAME,\
                                                         "preferences")
        if data == None or type(data) != type (dict()):
            self.preferences = self.DEFAULT_PREFERENCES
        else:
            self.preferences = data

    def preferences_store(self):
        self.plugin_api.save_configuration_object(self.PLUGIN_NAME,\
                                                  "preferences", \
                                                  self.preferences)

    def preferences_apply(self):
        if self.plugin_api.is_browser():
            if self.preferences["start_minimized"]:
                self.plugin_api.get_browser().start_minimized = True
            else:
                self.plugin_api.get_browser().start_minimized = False

    def preference_dialog_init(self): 
        self.builder = gtk.Builder()
        self.builder.add_from_file(os.path.dirname(os.path.abspath(__file__)) +\
                                   "/notification_area.ui")
        self.preferences_dialog = self.builder.get_object("preferences_dialog")
        self.chbox_miminized    = self.builder.get_object("pref_chbox_minimized")
        SIGNAL_CONNECTIONS_DIC = {
            "on_preferences_dialog_delete_event":
                self.on_preferences_cancel,
            "on_btn_preferences_cancel_clicked":
                self.on_preferences_cancel,
            "on_btn_preferences_ok_clicked":
                self.on_preferences_ok
        }
        self.builder.connect_signals(SIGNAL_CONNECTIONS_DIC)
