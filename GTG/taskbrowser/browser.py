# -*- coding: utf-8 -*-
# pylint: disable-msg=W0201
# -----------------------------------------------------------------------------
# Getting Things Gnome! - a personal organizer for the GNOME desktop
# Copyright (c) 2008-2009 - Lionel Dricot & Bertrand Rousseau
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
# -----------------------------------------------------------------------------


#=== IMPORT ===================================================================
#system imports
import pygtk
pygtk.require('2.0')
import gobject
import os
import gtk
import locale
import re
import datetime
import threading
import time
import subprocess
from Cheetah.Template import Template
from xdg.BaseDirectory import xdg_config_home

#our own imports
import GTG
from GTG import info
from GTG import _
from GTG.core.task                    import Task
from GTG.core.tagstore                import Tag
from GTG.taskeditor.editor            import TaskEditor
from GTG.taskbrowser                  import GnomeConfig
from GTG.taskbrowser                  import tasktree
from GTG.taskbrowser.tasktree         import TaskTreeModel,\
                                             ActiveTaskTreeView,\
                                             ClosedTaskTreeView
from GTG.taskbrowser                  import tagtree
from GTG.taskbrowser.tagtree          import TagTreeModel,\
                                             TagTreeView
from GTG.tools                        import openurl
from GTG.tools.dates                  import strtodate,\
                                             no_date,\
                                             RealDate
from GTG.core.plugins.manager         import PluginManager
from GTG.core.plugins.engine          import PluginEngine
from GTG.core.plugins.api             import PluginAPI

#=== OBJECTS ==================================================================

#=== MAIN CLASS ===============================================================

WINDOW_TITLE = "Getting Things GNOME!"

#Some default preferences that we should save in a file
WORKVIEW           = False
SIDEBAR            = False
CLOSED_PANE        = False
QUICKADD_PANE      = True
TOOLBAR            = True
BG_COLOR           = True
#EXPERIMENTAL_NOTES = False
TIME = 0

class Timer:
    def __init__(self,st):
        self.st = st
    def __enter__(self): self.start = time.time()
    def __exit__(self, *args): 
        print "%s : %s" %(self.st,time.time() - self.start)

class TaskBrowser:

    def __init__(self, requester, config, logger=None):

        self.logger=logger

        # Object prime variables
        self.priv   = {}
        self.req    = requester
        self.config = config.conf_dict
        self.task_config = config.task_conf_dict

        ### YOU CAN DEFINE YOUR INTERNAL MECHANICS VARIABLES BELOW
        # Task deletion
        self.tid_todelete = None # The tid that will be deleted
        # Editors
        self.opened_task  = {}   # This is the list of tasks that are already
                                 # opened in an editor of course it's empty
                                 # right now

        # Setup default values for view
        self._init_browser_config()

        # Setup GTG icon theme
        self._init_icon_theme()

        # Set up models
        self._init_models()

        # Load window tree
        self.builder = gtk.Builder() 
        self.builder.add_from_file(GnomeConfig.GLADE_FILE)

        # Define aliases for specific widgets
        self._init_widget_aliases()

        # Init non-glade widgets
        self._init_ui_widget()

        #Set the tooltip for the toolbar buttons
        self._init_toolbar_tooltips()

        # Initialize "About" dialog
        self._init_about_dialog()

        #Create our dictionay and connect it
        self._init_signal_connections()

        # Setting the default for the view
        # When there is no config, this should define the first configuration
        # of the UI
        self._init_view_defaults()

        # Define accelerator keys
        self._init_accelerators()
        
        # Initialize the plugin-engine
        self.p_apis = [] #the list of each plugin apis.
        self._init_plugin_engine()
        self.pm = None #the plugin manager window
        
        self.refresh_lock = threading.Lock()

        # NOTES
        #self._init_note_support()

### INIT HELPER FUNCTIONS #####################################################
#
    def _init_browser_config(self):
        self.priv["collapsed_tids"]           = []
        self.priv["tasklist"]                 = {}
        self.priv["tasklist"]["sort_column"]  = None
        self.priv["tasklist"]["sort_order"]   = gtk.SORT_ASCENDING
        self.priv["ctasklist"]                = {}
        self.priv["ctasklist"]["sort_column"] = None
        self.priv["ctasklist"]["sort_order"]  = gtk.SORT_ASCENDING
        self.priv['selected_rows']            = None
        self.priv['workview']                 = False
        #self.priv['noteview']                = False
        self.priv['filter_cbs']               = []
        self.priv['quick_add_cbs']            = []

    def _init_icon_theme(self):
        icon_dirs = [GTG.DATA_DIR, os.path.join(GTG.DATA_DIR, "icons")]
        for i in icon_dirs:
            gtk.icon_theme_get_default().prepend_search_path(i)
            gtk.window_set_default_icon_name("gtg")

    def _init_models(self):

        # Base models
        self.task_tree_model = TaskTreeModel(requester=self.req)
        
        # Active Tasks
        self.task_modelfilter = self.task_tree_model.filter_new()
        self.task_modelfilter.set_visible_func(self.active_task_visible_func)
        self.task_modelsort = gtk.TreeModelSort(self.task_modelfilter)
        self.task_modelsort.set_sort_func(\
            tasktree.COL_DDATE, self.dleft_sort_func)
        self.task_modelsort.set_sort_func(\
            tasktree.COL_DLEFT, self.dleft_sort_func)
        
        # Closed Tasks: dismissed and done
        self.ctask_modelfilter = self.task_tree_model.filter_new()
        self.ctask_modelfilter.set_visible_func(self.closed_task_visible_func)
        self.ctask_modelsort = gtk.TreeModelSort(self.ctask_modelfilter)
        
        # Tags
        self.tag_model = TagTreeModel(requester=self.req)
        self.tag_modelfilter = self.tag_model.filter_new()
        self.tag_modelfilter.set_visible_func(self.tag_visible_func)
        self.tag_modelsort = gtk.TreeModelSort(self.tag_modelfilter)
        self.tag_modelsort.set_sort_func(\
            tagtree.COL_ID, self.tag_sort_func)

        # Build the "all tags tag"
        self.alltag_tag = Tag("gtg-tags-all")
        self.alltag_tag.set_attribute("special","all")
        self.alltag_tag.set_attribute("label","<span weight='bold'>%s</span>"\
                                             % _("All tasks"))
        self.alltag_tag.set_attribute("icon","gtg-tags-all")
        self.alltag_tag.set_attribute("order",0)
        # Build the "without tag tag"
        self.notag_tag = Tag("gtg-tags-none")
        self.notag_tag.set_attribute("special","notag")
        self.notag_tag.set_attribute("label","<span weight='bold'>%s</span>"\
                                             % _("Tasks with no tags"))
        self.notag_tag.set_attribute("icon","gtg-tags-none")
        self.notag_tag.set_attribute("order",1)
        # Build the separator
        self.sep_tag = Tag("gtg-tags-sep")
        self.sep_tag.set_attribute("special","sep")
        self.sep_tag.set_attribute("order",2)
        # Add them to the model
        self.tag_model.add_tag(self.alltag_tag.get_name(), self.alltag_tag)
        self.tag_model.add_tag(self.notag_tag.get_name(), self.notag_tag)
        self.tag_model.add_tag(self.sep_tag.get_name(), self.sep_tag)

    def _init_widget_aliases(self):
        self.window             = self.builder.get_object("MainWindow")
        self.tagpopup           = self.builder.get_object("TagContextMenu")
        self.taskpopup          = self.builder.get_object("TaskContextMenu")
        self.ctaskpopup = \
            self.builder.get_object("ClosedTaskContextMenu")
        self.editbutton         = self.builder.get_object("edit_b")
        self.donebutton         = self.builder.get_object("mark_as_done_b")
        self.newtask            = self.builder.get_object("new_task_b")
        self.newsubtask         = self.builder.get_object("new_subtask_b")
        self.dismissbutton      = self.builder.get_object("dismiss")
        self.about              = self.builder.get_object("aboutdialog1")
        self.edit_mi            = self.builder.get_object("edit_mi")
        self.main_pane          = self.builder.get_object("main_pane")
        self.menu_view_workview = self.builder.get_object("view_workview")
        self.toggle_workview    = self.builder.get_object("workview_toggle")
        self.quickadd_entry     = self.builder.get_object("quickadd_field")
        self.closed_pane        = self.builder.get_object("closed_pane")
        self.toolbar            = self.builder.get_object("task_tb")
        self.quickadd_pane      = self.builder.get_object("quickadd_pane")
        self.sidebar            = self.builder.get_object("sidebar")
        self.sidebar_container  = self.builder.get_object("sidebar-scroll")
        self.export_dialog      = self.builder.get_object("export_dialog")
        self.export_combo_templ = self.builder.get_object("export_combo_templ")
        self.export_image       = self.builder.get_object("export_image")
        # Tree views
        #self.tags_tv             = self.builder.get_object("tag_tview")
        # NOTES
        #self.new_note_button    = self.builder.get_object("new_note_button")
        #self.note_toggle        = self.builder.get_object("note_toggle")

    def _init_ui_widget(self):
        # The Active tasks treeview
        self.task_tv = ActiveTaskTreeView()
        self.task_tv.set_model(self.task_modelsort)
        self.main_pane.add(self.task_tv)

        # The done/dismissed taks treeview
        self.ctask_tv = ClosedTaskTreeView()
        self.ctask_tv.set_model(self.ctask_modelsort)
        self.closed_pane.add(self.ctask_tv)

        # The tags treeview
        self.tags_tv = TagTreeView()
        self.tags_tv.set_model(self.tag_modelsort)
        self.tags_tv.expand_row('0', True)
        self.sidebar_container.add(self.tags_tv)

    def _init_toolbar_tooltips(self):
        self.donebutton.set_tooltip_text(GnomeConfig.MARK_DONE_TOOLTIP)
        self.editbutton.set_tooltip_text(GnomeConfig.EDIT_TOOLTIP)
        self.dismissbutton.set_tooltip_text(GnomeConfig.MARK_DISMISS_TOOLTIP)
        self.newtask.set_tooltip_text(GnomeConfig.NEW_TASK_TOOLTIP)
        self.newsubtask.set_tooltip_text(GnomeConfig.NEW_SUBTASK_TOOLTIP)
        self.toggle_workview.set_tooltip_text(\
            GnomeConfig.WORKVIEW_TOGGLE_TOOLTIP)

    def _init_about_dialog(self):
        gtk.about_dialog_set_url_hook(lambda dialog, url: openurl.openurl(url))
        self.about.set_website(info.URL)
        self.about.set_website_label(info.URL)
        self.about.set_version(info.VERSION)
        self.about.set_authors(info.AUTHORS)
        self.about.set_artists(info.ARTISTS)
        self.about.set_translator_credits(info.TRANSLATORS)

    def _init_signal_connections(self):

        SIGNAL_CONNECTIONS_DIC = {
#            "on_force_refresh":
#                self.on_force_refresh,
            "on_add_task":
                self.on_add_task,
            "on_add_note":
                (self.on_add_task, 'Note'),
            "on_edit_active_task":
                self.on_edit_active_task,
            "on_edit_done_task":
                self.on_edit_done_task,
#            "on_edit_note":
#                self.on_edit_note,
            "on_delete_task":
                self.on_delete_task,
            "on_mark_as_done":
                self.on_mark_as_done,
            "on_dismiss_task":
                self.on_dismiss_task,
            "on_delete":
                self.on_delete,
            "on_move":
                self.on_move,
            "on_size_allocate":
                self.on_size_allocate,
            "on_file_export_activate":
                self.on_export,
            "gtk_main_quit":
                self.on_close,
            "on_delete_confirm":
                self.on_delete_confirm,
            "on_delete_cancel":
                lambda x: x.hide,
            "on_add_subtask":
                self.on_add_subtask,
            "on_colorchooser_activate":
                self.on_colorchooser_activate,
            "on_workview_toggled":
                self.on_workview_toggled,
            "on_note_toggled":
                self.on_note_toggled,
            "on_view_workview_toggled":
                self.on_workview_toggled,
            "on_view_closed_toggled":
                self.on_closed_toggled,
            "on_view_sidebar_toggled":
                self.on_sidebar_toggled,
            "on_bg_color_toggled":
                self.on_bg_color_toggled,
            "on_quickadd_field_activate":
                self.on_quickadd_activate,
            "on_quickadd_button_activate":
                self.on_quickadd_activate,
            "on_view_quickadd_toggled":
                self.on_toggle_quickadd,
            "on_view_toolbar_toggled":
                self.on_toolbar_toggled,
            "on_about_clicked":
                self.on_about_clicked,
            "on_about_delete":
                self.on_about_close,
            "on_about_close":
                self.on_about_close,
            "on_nonworkviewtag_toggled":
                self.on_nonworkviewtag_toggled,
            "on_pluginmanager_activate": 
                self.on_pluginmanager_activate,
            "on_export_btn_open_clicked": 
                self.on_export_open,
            "on_export_btn_save_clicked": 
                self.on_export_save,
            "on_export_dialog_delete_event": 
                self.on_export_cancel,
            "on_export_combo_templ_changed":
                self.on_export_combo_changed
        }

        self.builder.connect_signals(SIGNAL_CONNECTIONS_DIC)

        if (self.window):
            self.window.connect("destroy", gtk.main_quit)

        # Active tasks TreeView
        self.task_tv.connect('row-activated',\
            self.on_edit_active_task)
        self.task_tv.connect('button-press-event',\
            self.on_task_treeview_button_press_event)
        self.task_tv.connect('key-press-event',\
            self.on_task_treeview_key_press_event)
        
        # Closed tasks TreeView
        self.ctask_tv.connect('row-activated',\
            self.on_edit_done_task)
        self.ctask_tv.connect('button-press-event',\
            self.on_closed_task_treeview_button_press_event)
        self.ctask_tv.connect('key-press-event',\
            self.on_closed_task_treeview_key_press_event)

        # Closed tasks TreeView
        self.tags_tv.connect('cursor-changed',\
            self.on_select_tag)
        self.tags_tv.connect('row-activated',\
            self.on_select_tag)
        self.tags_tv.connect('button-press-event',\
            self.on_tag_treeview_button_press_event)

        # Connect requester signals to TreeModels
        self.req.connect("task-added", self.on_task_added) 
        self.req.connect("task-deleted", self.on_task_deleted)
        self.req.connect("task-modified", self.on_task_modified)
        
        # Connect signals from models
        self.task_modelsort.connect("row-has-child-toggled", self.on_child_toggled)

    def _init_view_defaults(self):
        self.menu_view_workview.set_active(WORKVIEW)
        self.builder.get_object("view_sidebar").set_active(SIDEBAR)
        self.builder.get_object("view_closed").set_active(CLOSED_PANE)
        self.builder.get_object("view_quickadd").set_active(QUICKADD_PANE)
        self.builder.get_object("view_toolbar").set_active(TOOLBAR)
        self.priv["bg_color_enable"] = BG_COLOR
        # Set sorting order
        self.task_modelsort.set_sort_column_id(\
            tasktree.COL_DLEFT, gtk.SORT_ASCENDING)
        self.ctask_modelsort.set_sort_column_id(\
            tasktree.COL_CDATE, gtk.SORT_DESCENDING)
        self.tag_modelsort.set_sort_column_id(\
            tagtree.COL_ID, gtk.SORT_ASCENDING)

    def _init_accelerators(self):

        agr = gtk.AccelGroup()
        self.builder.get_object("MainWindow").add_accel_group(agr)

        view_sidebar = self.builder.get_object("view_sidebar")
        key, mod     = gtk.accelerator_parse("F9")
        view_sidebar.add_accelerator("activate", agr, key, mod,\
            gtk.ACCEL_VISIBLE)

        file_quit = self.builder.get_object("file_quit")
        key, mod  = gtk.accelerator_parse("<Control>q")
        file_quit.add_accelerator("activate", agr, key, mod, gtk.ACCEL_VISIBLE)

        edit_undo = self.builder.get_object("edit_undo")
        key, mod  = gtk.accelerator_parse("<Control>z")
        edit_undo.add_accelerator("activate", agr, key, mod, gtk.ACCEL_VISIBLE)

        edit_redo = self.builder.get_object("edit_redo")
        key, mod  = gtk.accelerator_parse("<Control>y")
        edit_redo.add_accelerator("activate", agr, key, mod, gtk.ACCEL_VISIBLE)

        new_task_mi = self.builder.get_object("new_task_mi")
        key, mod    = gtk.accelerator_parse("<Control>n")
        new_task_mi.add_accelerator("activate", agr, key, mod,\
            gtk.ACCEL_VISIBLE)

        new_subtask_mi = self.builder.get_object("new_subtask_mi")
        key, mod       = gtk.accelerator_parse("<Control><Shift>n")
        new_subtask_mi.add_accelerator("activate", agr, key, mod,\
            gtk.ACCEL_VISIBLE)

        edit_button = self.builder.get_object("edit_b")
        key, mod    = gtk.accelerator_parse("<Control>e")
        edit_button.add_accelerator("clicked", agr, key, mod,\
            gtk.ACCEL_VISIBLE)

        quickadd_field = self.builder.get_object('quickadd_field')
        key, mod = gtk.accelerator_parse('<Control>l')
        quickadd_field.add_accelerator(
            'grab-focus', agr, key, mod, gtk.ACCEL_VISIBLE)

        mark_done_mi = self.builder.get_object('mark_done_mi')
        key, mod = gtk.accelerator_parse('<Control>d')
        mark_done_mi.add_accelerator(
            'activate', agr, key, mod, gtk.ACCEL_VISIBLE)

        task_dismiss = self.builder.get_object('task_dismiss')
        key, mod = gtk.accelerator_parse('<Control>i')
        task_dismiss.add_accelerator(
            'activate', agr, key, mod, gtk.ACCEL_VISIBLE)
        
    def _init_plugin_engine(self):
        # plugins - Init
        self.pengine = PluginEngine(GTG.PLUGIN_DIR)
        # loads the plugins in the plugin dir
        self.plugins = self.pengine.LoadPlugins()
        
        # initializes the plugin api class
        self.plugin_api = PluginAPI(self.window, self.config, GTG.DATA_DIR, self.builder,\
                                    self.req, self.task_tv, self.priv['filter_cbs'],\
                                    self.tagpopup, self.tags_tv, None, None,\
                                    self.priv['quick_add_cbs'])
        self.p_apis.append(self.plugin_api)
        
        if self.plugins:
            # checks the conf for user settings
            if self.config.has_key("plugins"):
                if self.config["plugins"].has_key("enabled"):
                    plugins_enabled = self.config["plugins"]["enabled"]
                    for p in self.plugins:
                        if p['name'] in plugins_enabled:
                            p['state'] = True
                        
                if self.config["plugins"].has_key("disabled"):
                    plugins_disabled = self.config["plugins"]["disabled"]
                    for p in self.plugins:    
                        if p['name'] in plugins_disabled:
                            p['state'] = False
            
            # initializes and activates each plugin (that is enabled)
            self.pengine.activatePlugins(self.plugins, self.p_apis)

#    def _init_note_support(self):
#        self.notes  = EXPERIMENTAL_NOTES
#        # Hide notes if disabled
#        if not self.notes:
#            self.note_toggle.hide()
#            self.new_note_button.hide()
#        #Set the tooltip for the toolbar button
#        self.new_note_button.set_tooltip_text("Create a new note")
#        self.note_tview = self.builder.get_object("note_tview")
#        self.note_tview = gtk.TreeView()
#        self.note_tview.connect("row-activated", self.on_edit_note)
#        self.note_tview.show()
#        self.note_ts    = gtk.TreeStore(gobject.TYPE_PYOBJECT, str, str)

### HELPER FUNCTIONS ##########################################################
#
    def restore_state_from_conf(self):

        # Extract state from configuration dictionary
        if not "browser" in self.config:
            return

        if ("width" in self.config["browser"] and
            "height" in self.config["browser"]):
            width = int(self.config["browser"]["width"])
            height = int(self.config["browser"]["height"])
            self.window.resize(width, height)

        if ("x_pos" in self.config["browser"] and
            "y_pos" in self.config["browser"]):

            xpos = int(self.config["browser"]["x_pos"])
            ypos = int(self.config["browser"]["y_pos"])
            self.window.move(xpos, ypos)

        if "tag_pane" in self.config["browser"]:
            tag_pane = eval(self.config["browser"]["tag_pane"])
            if not tag_pane:
                self.builder.get_object("view_sidebar").set_active(False)
                self.sidebar.hide()
            else:
                self.builder.get_object("view_sidebar").set_active(True)
                self.sidebar.show()

        if "closed_task_pane" in self.config["browser"]:
            closed_task_pane = eval(
                self.config["browser"]["closed_task_pane"])
            if not closed_task_pane:
                self.closed_pane.hide()
                self.builder.get_object("view_closed").set_active(False)
            else:
                self.closed_pane.show()
                self.builder.get_object("view_closed").set_active(True)

        if "ctask_pane_height" in self.config["browser"]:
            ctask_pane_height = eval(
                self.config["browser"]["ctask_pane_height"])
            self.builder.get_object("vpaned1").set_position(ctask_pane_height)

        if "toolbar" in self.config["browser"]:
            toolbar = eval(self.config["browser"]["toolbar"])
            if not toolbar:
                self.toolbar.hide()
                self.builder.get_object("view_toolbar").set_active(False)

        if "quick_add" in self.config["browser"]:
            quickadd_pane = eval(self.config["browser"]["quick_add"])
            if not quickadd_pane:
                self.quickadd_pane.hide()
                self.builder.get_object("view_quickadd").set_active(False)

        if "bg_color_enable" in self.config["browser"]:
            bgcol_enable = eval(self.config["browser"]["bg_color_enable"])
            self.priv["bg_color_enable"] = bgcol_enable
            self.builder.get_object("bgcol_enable").set_active(bgcol_enable)

        if "collapsed_tasks" in self.config["browser"]:
            self.priv["collapsed_tids"] = self.config[
                "browser"]["collapsed_tasks"]

        if "tasklist_sort" in self.config["browser"]:
            col_id, order = self.config["browser"]["tasklist_sort"]
            self.priv["sort_column"] = col_id
            try:
                col_id, order = int(col_id), int(order)
                self.priv["tasklist"]["sort_column"] = col_id
                if order == 0:
                    self.priv["tasklist"]["sort_order"] = gtk.SORT_ASCENDING
                if order == 1:
                    self.priv["tasklist"]["sort_order"] = gtk.SORT_DESCENDING
                self.task_modelsort.set_sort_column_id(\
                    col_id,\
                    self.priv["tasklist"]["sort_order"])
            except:
                print "Invalid configuration for sorting columns"

        if "view" in self.config["browser"]:
            view = self.config["browser"]["view"]
            if view == "workview":
                self.do_toggle_workview()
                
        if "opened_tasks" in self.config["browser"]:
            odic = self.config["browser"]["opened_tasks"]
            for t in odic:
                ted = self.open_task(t)
                #restoring position doesn't work, I don't know why
                #ted.move(odic[t][0],odic[t][1])

#        if "experimental_notes" in self.config["browser"]:
#            self.notes = eval(self.config["browser"]["experimental_notes"])
#            if self.notes:
#                self.note_toggle.show()
#                self.new_note_button.show()
#            else:
#                self.note_toggle.hide()
#                self.new_note_button.hide()

    def count_tasks_rec(self, my_task, active_tasks):
        count = 0
        for t in my_task.get_subtasks():
            if t.get_id() in active_tasks:
                if len(t.get_subtasks()) != 0:
                    count = count + 1 + self.count_tasks_rec(t, active_tasks)
                else:
                    count = count + 1
        return count

    def _count_subtask(self, model, iter):
        count = 0
        c = model.iter_children(iter)
        while c:
            count = count + 1 + self._count_subtask(model, c)
            c = model.iter_next(c)
        return count

    def do_toggle_workview(self):
        #We have to be careful here to avoid a loop of signals
        #menu_state   = self.menu_view_workview.get_active()
        #button_state = self.toggle_workview.get_active()
        #We cannot have note and workview at the same time
#        if not self.priv['workview'] and self.note_toggle.get_active():
#            self.note_toggle.set_active(False)
        #We do something only if both widget are in different state
        self.task_modelsort.foreach(self.update_collapsed_row, None)
        tobeset = not self.priv['workview']
        self.menu_view_workview.set_active(tobeset)
        self.toggle_workview.set_active(tobeset)
        self.priv['workview'] = tobeset
        self.tag_model.set_workview(self.priv['workview'])
        self.task_modelfilter.refilter()
        self.tag_modelfilter.refilter()
        self._update_window_title()

    def _update_window_title(self):
        count = self.get_n_active_tasks()
        #Set the title of the window:
        parenthesis = ""
        if count == 0:
            parenthesis = _("(no active tasks)")
        elif count == 1:
            parenthesis = _("(1 active task)")
        else:
            parenthesis = _("(%s active tasks)") % count
        self.window.set_title(WINDOW_TITLE + " %s" % parenthesis)

    def get_canonical_date(self, arg):
        """
        Transform "arg" in a valid yyyy-mm-dd date or return None.
        "arg" can be a yyyy-mm-dd, yyyymmdd, mmdd, today or a weekday name.
        """
        day_names_en = ["monday", "tuesday", "wednesday", "thursday",
                        "friday", "saturday", "sunday"]
        day_names = [_("monday"), _("tuesday"), _("wednesday"),
                     _("thursday"), _("friday"), _("saturday"),
                     _("sunday")]
        if re.match(r'\d{4}-\d{2}-\d{2}', arg):
            date = arg
        elif arg.isdigit():
            if len(arg) == 8:
                date = "%s-%s-%s" % (arg[:4], arg[4:6], arg[6:])
            elif len(arg) == 4:
                year = datetime.date.today().year
                date = "%i-%s-%s" % (year, arg[:2], arg[2:])
        elif arg.lower() == "today" or arg.lower() == _("today"):
            today = datetime.date.today()
            year = today.year
            month = today.month
            day = today.day
            date = "%i-%i-%i" % (year, month, day)
        elif arg.lower() == "tomorrow" or\
          arg.lower() == _("tomorrow"):
            today = datetime.date.today()
            tomorrow = today + datetime.timedelta(days=1)
            year = tomorrow.year
            month = tomorrow.month
            day = tomorrow.day
            date = "%i-%i-%i" % (year, month, day)
        elif arg.lower() in day_names_en or arg.lower() in day_names:
            today = datetime.date.today()
            today_day = today.weekday()
            if arg.lower() in day_names_en:
                arg_day = day_names_en.index(arg.lower())
            else:
                arg_day = day_names.index(arg.lower())
            if arg_day > today_day:
                delta = datetime.timedelta(days = arg_day-today_day)
            else:
                delta = datetime.timedelta(days = arg_day-today_day+7)
            next_date = today + delta
            year = next_date.year
            month = next_date.month
            day = next_date.day
            date = "%i-%i-%i" % (year, month, day)
        elif arg in ('now', 'soon', 'later'):
            date = arg
        else:
            return no_date
        return strtodate(date)

    def update_collapsed_row(self, model, path, iter, user_data):
        """Build a list of task that must showed as collapsed in Treeview"""
        model = self.task_tv.get_model()
        tid   = model.get_value(iter, tasktree.COL_TID)
        # Remove expanded rows
        if (model.iter_has_child(iter) and
            self.task_tv.row_expanded(path) and
            tid in self.priv["collapsed_tids"]):
            self.priv["collapsed_tids"].remove(tid)
        # Append collapsed rows
        elif (model.iter_has_child(iter) and
              not self.task_tv.row_expanded(path) and
              tid not in self.priv["collapsed_tids"]):
            self.priv["collapsed_tids"].append(tid)

        return False # Return False or the TreeModel.foreach() function ends

    def open_task(self, uid,thisisnew=False):
        """Open the task identified by 'uid'.

        If a Task editor is already opened for a given task, we present it.
        Else, we create a new one.
        """
        t = self.req.get_task(uid)
        tv = None
        if uid in self.opened_task:
            tv = self.opened_task[uid]
            tv.present()
        elif t:
            tv = TaskEditor(
                self.req, t, self.plugins, \
                self.on_delete_task, self.close_task, self.open_task, \
                self.get_tasktitle,taskconfig=self.task_config, \
                plugin_apis=self.p_apis,thisisnew=thisisnew)
            #registering as opened
            self.opened_task[uid] = tv
        return tv

    def get_tasktitle(self, tid):
        task = self.req.get_task(tid)
        return task.get_title()

    def get_task_and_subtask_titles(self, tid):
        task = self.req.get_task(tid)
        titles_list = task.get_titles([])
        toreturn = ""
        for st in titles_list :
            toreturn = "%s\n- %s" %(toreturn,st) 
        return toreturn

    def close_task(self, tid):
        # When an editor is closed, it should deregister itself.
        if tid in self.opened_task:
            del self.opened_task[tid]

    def is_task_visible(self, task):
        """Returns True if the task meets the criterion to be displayed
        @param  task: the task to assess
        """

        tag_list, notag_only = self.get_selected_tags()

        if len(tag_list)==1: #include child tags
            tag_list = tag_list[0].all_children()

        if not task.has_tags(tag_list=tag_list, notag_only=notag_only):
            return False
        
        #if workview is enabled
        if self.priv['workview']:
            res = True
            
            # filter tasks view callbacks
            for cb in self.priv['filter_cbs']:
                res = cb(task.get_id())
                if res == False:
                    return False
            
            #we verify that the task is started
            if not task.is_started() :
                return False
                    
            #we verify that there is no non-workview tag for this task
            for t in task.get_tags():
                if t.get_attribute("nonworkview") and t not in tag_list:
                    res = res and (not eval(t.get_attribute("nonworkview")))
            return res and task.is_workable()
        else:
            return True

    def is_lineage_visible(self, task):
        """Returns True if at least one set of tasks that compose a lineage of
        the given task can be found where all the tasks meets the criterion
        to be displayed. (i.e.: there exists a chain of tasks from root to task
        that can all be displayed)
        @param task: the task whose lineage will be assessed
        """
        res = False
        parents = task.get_parents()
        for par_tid in parents:
            par_task = self.req.get_task(par_tid)
            if par_task.has_parents():
                res = res or (self.is_task_visible(par_task) and self.is_lineage_visible(par_task))
            else:
                res = res or self.is_task_visible(par_task)
        return res

    def active_task_visible_func(self, model, iter, user_data=None):
        """Return True if the row must be displayed in the treeview.
        @param model: the model of the filtered treeview
        @param iter: the iter whose visiblity must be evaluated
        @param user_data:
        """
        task = model.get_value(iter, tasktree.COL_OBJ)
        if not task or task.get_status() != Task.STA_ACTIVE:
            return False
        if not model.iter_parent(iter):
            return self.is_task_visible(task) and not self.is_lineage_visible(task)
        return self.is_task_visible(task)
               
    def closed_task_visible_func(self, model, iter, user_data=None):
        """Return True if the row must be displayed in the treeview.
        @param model: the model of the filtered treeview
        @param iter: the iter whose visiblity must be evaluated
        @param user_data:
        """
        tag_list, notag_only = self.get_selected_tags()
        task = model.get_value(iter, tasktree.COL_OBJ)
        return task.get_status() != Task.STA_ACTIVE and\
            not model.iter_parent(iter)
                  

    def tag_visible_func(self, model, iter, user_data=None):
        """Return True if the row must be displayed in the treeview.
        @param model: the model of the filtered treeview
        @param iter: the iter whose visiblity must be evaluated
        @param user_data:
        """
        tag = model.get_value(iter, tagtree.COL_OBJ)
        
        # show the tag if any children are shown
        child = model.iter_children(iter)
        while child:
            if self.tag_visible_func(model, child):
                return True
            child=model.iter_next(child)
        
        if not tag.get_attribute("special"):
            count = model.get_value(iter, tagtree.COL_COUNT)
            return count != '0'
        else:
            return True

    def dleft_sort_func(self, model, iter1, iter2, user_data=None):
        order = self.task_tv.get_model().get_sort_column_id()[1]
        task1 = model.get_value(iter1, tasktree.COL_OBJ)
        task2 = model.get_value(iter2, tasktree.COL_OBJ)
        t1_dleft = task1.get_due_date()
        t2_dleft = task2.get_due_date()
        
        sort = 0
        
        def reverse_if_descending(s):
            """Make a cmp() result relative to the top instead of following 
               user-specified sort direction"""
            if order == gtk.SORT_ASCENDING:
                return s
            else:
                return -1 * s
        
        # Always put no_date tasks on the bottom
        if not t1_dleft and t2_dleft:
            sort = reverse_if_descending(1)
        elif t1_dleft and not t2_dleft:
            sort = reverse_if_descending(-1)
        else:
            sort = cmp(t2_dleft, t1_dleft)
        
        if sort == 0:
            # Put fuzzy dates below real dates
            if isinstance(t1_dleft, RealDate) and not isinstance(t2_dleft, RealDate):
                sort = reverse_if_descending(-1)
            elif isinstance(t2_dleft, RealDate) and not isinstance(t1_dleft, RealDate):
                sort = reverse_if_descending(1)
                
            else:  # Break ties by sorting by title
                t1_title = task1.get_title()
                t2_title = task2.get_title()
                t1_title = locale.strxfrm(t1_title)
                t2_title = locale.strxfrm(t2_title)
                sort = reverse_if_descending( cmp(t1_title, t2_title) )
                
        return sort

    def tag_sort_func(self, model, iter1, iter2, user_data=None):
        order = self.tags_tv.get_model().get_sort_column_id()[1]
        t1 = model.get_value(iter1, tagtree.COL_OBJ)
        t2 = model.get_value(iter2, tagtree.COL_OBJ)
        t1_sp = t1.get_attribute("special")
        t2_sp = t2.get_attribute("special")
        t1_name = locale.strxfrm(t1.get_name())
        t2_name = locale.strxfrm(t2.get_name())
        if not t1_sp and not t2_sp:
            return cmp(t1_name, t2_name)
        elif not t1_sp and t2_sp:
            if order == gtk.SORT_ASCENDING:
                return 1
            else:
                return -1
        elif t1_sp and not t2_sp:
            if order == gtk.SORT_ASCENDING:
                return -1
            else:
                return 1
        else:
            t1_order = t1.get_attribute("order")
            t2_order = t2.get_attribute("order")
            if order == gtk.SORT_ASCENDING:
                return cmp(t1_order, t2_order)
            else:
                return cmp(t2_order, t1_order)            

    def empty_tree_model(self, model):
        if model == None: 
            return
        iter = model.get_iter_first()
        while iter:
            this_iter =  iter
            iter = model.iter_next(iter)
            model.remove(this_iter)

    def combo_list_store(self, list_store, list_obj):
        if list_store == None:
            list_store = gtk.ListStore(gobject.TYPE_STRING)
        self.empty_tree_model(list_store)
        for elem in list_obj:
            iter = list_store.append()
            list_store.set(iter, 0, elem)
        return self.export_list_store

    def combo_completion(self, list_store):
        completion = gtk.EntryCompletion()
        completion.set_minimum_key_length(0)
        completion.set_text_column(0)
        completion.set_inline_completion(True)
        completion.set_model(list_store)

    def combo_set_text(self, combobox, entry):
        model = combobox.get_model()
        index = combobox.get_active()
        if index > -1:
            entry.set_text(model[index][0])

    def combo_get_text(self, combobox):
        model = combobox.get_model()
        active = combobox.get_active()
        if active < 0:
            return None
        return model[active][0]

    def export_combo_decorator(self, combobox, list_obj):
        first_run = not hasattr(self, "export_combo_templ_entry")
        if first_run:
            self.export_combo_templ_entry = gtk.Entry()
            combobox.add(self.export_combo_templ_entry)
            self.export_list_store = gtk.ListStore(gobject.TYPE_STRING)
            self.export_combo_templ_entry.set_completion(
                        self.combo_completion(self.export_list_store))
            combobox.set_model(self.export_list_store)
            combobox.connect('changed', self.combo_set_text,
                         self.export_combo_templ_entry )
            #render the combo-box drop down menu
            cell = gtk.CellRendererText()
            combobox.pack_start(cell, True)
            combobox.add_attribute(cell, 'text', 0) 
        #check if Clipboard contains an element of the list
        clipboard = gtk.Clipboard()
        def clipboardCallback(clipboard, text, list_obj):
            if len(filter(lambda x: x == text, list_obj)) != 0:
                entry.set_text(text)
        clipboard.request_text(clipboardCallback, list_obj)
       #wrap the combo-box if it's too long
        if len(list_obj) > 15:
            combobox.set_wrap_width(5)
        #populate the combo-box
        self.combo_list_store(self.export_list_store, list_obj)
        if not hasattr(self, "export_combo_active"):
            self.export_combo_active = 0
        combobox.set_active(self.export_combo_active)

    def get_user_dir(self, key):
        """
        http://www.freedesktop.org/wiki/Software/xdg-user-dirs
            XDG_DESKTOP_DIR
            XDG_DOWNLOAD_DIR
            XDG_TEMPLATES_DIR
            XDG_PUBLICSHARE_DIR
            XDG_DOCUMENTS_DIR
            XDG_MUSIC_DIR
            XDG_PICTURES_DIR
            XDG_VIDEOS_DIR

        Taken from FrontBringer
        (distributed under the GNU GPL v3 license),
        courtesy of Jean-François Fortin Tam.
        """
        user_dirs_dirs = os.path.expanduser(xdg_config_home + "/user-dirs.dirs")
        if os.path.exists(user_dirs_dirs):
            f = open(user_dirs_dirs, "r")
            for line in f.readlines():
                if line.startswith(key):
                    return os.path.expandvars(line[len(key)+2:-2])

### SIGNAL CALLBACKS ##########################################################
# Typically, reaction to user input & interactions with the GUI
#
    def register_filter_callback(self, cb):
        if cb not in self.priv['filter_cbs']:
            self.priv['filter_cbs'].append(cb)
        
    def unregister_filter_callback(self, cb):
        if cb in self.priv['filter_cbs']:
            self.priv['filter_cbs'].remove(cb)
        
    def on_move(self, widget, data):
        xpos, ypos = self.window.get_position()
        self.priv["window_xpos"] = xpos
        self.priv["window_ypos"] = ypos

    def on_size_allocate(self, widget, data):
        width, height = self.window.get_size()
        self.priv["window_width"]  = width
        self.priv["window_height"] = height

    def on_delete(self, widget, user_data):

        # Save expanded rows
        self.task_tv.get_model().foreach(self.update_collapsed_row, None)

        # Cleanup collapsed row list
        for tid in self.priv["collapsed_tids"]:
            if not self.req.has_task(tid):
                self.priv["collapsed_tids"].remove(tid)

        # Get configuration values
        tag_sidebar        = self.sidebar.get_property("visible")
        closed_pane        = self.closed_pane.get_property("visible")
        quickadd_pane      = self.quickadd_pane.get_property("visible")
        toolbar            = self.toolbar.get_property("visible")
        #task_tv_sort_id    = self.task_ts.get_sort_column_id()
        sort_column, sort_order = self.task_modelsort.get_sort_column_id()
        closed_pane_height = self.builder.get_object("vpaned1").get_position()

        if self.priv['workview']:
            view = "workview"
        else:
            view = "default"
            
        # plugins are deactivated
        if self.plugins:
            self.pengine.deactivatePlugins(self.plugins, self.p_apis)
            
        #save opened tasks and their positions.
        open_task = []
        for otid in self.opened_task.keys():     
            open_task.append(otid)
            self.opened_task[otid].close()

        # Populate configuration dictionary
        self.config["browser"] = {
            'width':
                self.priv["window_width"],
            'height':
                self.priv["window_height"],
            'x_pos':
                self.priv["window_xpos"],
            'y_pos':
                self.priv["window_ypos"],
            'bg_color_enable':
                self.priv["bg_color_enable"],
            'collapsed_tasks':
                self.priv["collapsed_tids"],
            'tag_pane':
                tag_sidebar,
            'closed_task_pane':
                closed_pane,
            'ctask_pane_height':
                closed_pane_height,
            'toolbar':
                toolbar,
            'quick_add':
                quickadd_pane,
            'view':
                view,
            'opened_tasks':
                open_task,
            }
        if   sort_column is not None and sort_order == gtk.SORT_ASCENDING:
            self.config["browser"]["tasklist_sort"]  = [sort_column, 0]
        elif sort_column is not None and sort_order == gtk.SORT_DESCENDING:
            self.config["browser"]["tasklist_sort"]  = [sort_column, 1]
        self.config["browser"]["view"] = view
#        if self.notes:
#            self.config["browser"]["experimental_notes"] = True
        
        # adds the plugin settings to the conf
        if self.plugins:
            self.config["plugins"] = {}
            self.config["plugins"]["disabled"] =\
                self.pengine.disabledPlugins(self.plugins)
            self.config["plugins"]["enabled"] =\
                self.pengine.enabledPlugins(self.plugins)

    def on_force_refresh(self, widget):
        if self.refresh_lock.acquire(False):
            gobject.idle_add(self.general_refresh)

    def on_about_clicked(self, widget):
        self.about.show()

    def on_about_close(self, widget, response):
        self.about.hide()
        return True

    def on_color_changed(self, widget):
        gtkcolor = widget.get_current_color()
        strcolor = gtk.color_selection_palette_to_string([gtkcolor])
        tags, notag_only = self.get_selected_tags()
        for t in tags:
            t.set_attribute("color", strcolor)
        self.task_tv.refresh()
        self.tags_tv.refresh()

    def on_colorchooser_activate(self, widget):
        #TODO: Color chooser should be refactorized in its own class. Well, in
        #fact we should have a TagPropertiesEditor (like for project) Also,
        #color change should be immediate. There's no reason for a Ok/Cancel
        dialog = gtk.ColorSelectionDialog('Choose color')
        colorsel = dialog.colorsel
        colorsel.connect("color_changed", self.on_color_changed)
        # Get previous color
        tags, notag_only = self.get_selected_tags()
        init_color = None
        if len(tags) == 1:
            color = tags[0].get_attribute("color")
            if color != None:
                colorspec = gtk.gdk.color_parse(color)
                colorsel.set_previous_color(colorspec)
                colorsel.set_current_color(colorspec)
                init_color = colorsel.get_current_color()
        response = dialog.run()
        # Check response and set color if required
        if response != gtk.RESPONSE_OK and init_color:
            strcolor = gtk.color_selection_palette_to_string([init_color])
            tags, notag_only = self.get_selected_tags()
            for t in tags:
                t.set_attribute("color", strcolor)
        self.task_tv.refresh()
        dialog.destroy()

    def on_workview_toggled(self, widget):
        self.do_toggle_workview()

    def on_sidebar_toggled(self, widget):
        view_sidebar = self.builder.get_object("view_sidebar")
        if self.sidebar.get_property("visible"):
            view_sidebar.set_active(False)
            self.sidebar.hide()
        else:
            view_sidebar.set_active(True)
            self.sidebar.show()

    def on_note_toggled(self, widget):
        self.priv['noteview'] = not self.priv['noteview']
        workview_state = self.toggle_workview.get_active()
        if workview_state:
            self.toggle_workview.set_active(False)
        #self.do_refresh()

    def on_closed_toggled(self, widget):
        if widget.get_active():
            self.closed_pane.show()
        else:
            self.closed_pane.hide()

    def on_bg_color_toggled(self, widget):
        if widget.get_active():
            self.priv["bg_color_enable"] = True
            self.task_tree_model.set_bg_color(True)
        else:
            self.priv["bg_color_enable"] = False
            self.task_tree_model.set_bg_color(False)
        self.task_tv.refresh()
        self.ctask_tv.refresh()

    def on_toolbar_toggled(self, widget):
        if widget.get_active():
            self.toolbar.show()
        else:
            self.toolbar.hide()

    def on_toggle_quickadd(self, widget):
        if widget.get_active():
            self.quickadd_pane.show()
        else:
            self.quickadd_pane.hide()

    def on_child_toggled(self, model, path, iter):
        #print "on_child_toggled: %s" % model.get_value(iter, tasktree.COL_TID)
        tid = model.get_value(iter, tasktree.COL_TID)
        if tid not in self.priv.get("collapsed_tids", []):
            self.task_tv.expand_row(path, True)

    def on_quickadd_activate(self, widget):
        text = self.quickadd_entry.get_text()
        due_date = no_date
        defer_date = no_date
        if text:
            tags, notagonly = self.get_selected_tags()
            # Get tags in the title
            for match in re.findall(r'[\s](@[^@,\s]+)', text):
                tags.append(GTG.core.tagstore.Tag(match))
                # Remove the @
                #text =text.replace(match,match[1:],1)
            # Get attributes
            regexp = r'([\s]*)([a-zA-Z0-9_-]+):([^\s]+)'
            for spaces, attribute, args in re.findall(regexp, text):
                valid_attribute = True
                if attribute.lower() == "tags" or \
                   attribute.lower() == _("tags"):
                    for tag in args.split(","):
                        tags.append(GTG.core.tagstore.Tag("@"+tag))
                elif attribute.lower() == "defer" or \
                     attribute.lower() == _("defer"):
                    defer_date = self.get_canonical_date(args)
                    if not defer_date:
                        valid_attribute = False
                elif attribute.lower() == "due" or \
                     attribute.lower() == _("due"):
                    due_date = self.get_canonical_date(args)
                    if not due_date:
                        valid_attribute = False
                else:
                    # attribute is unknown
                    valid_attribute = False
                if valid_attribute:
                    # if the command is valid we have to remove it
                    # from the task title
                    text = \
                        text.replace("%s%s:%s" % (spaces, attribute, args), "")
            # Create the new task
            task = self.req.new_task(tags=tags, newtask=True)
            if text != "":
                task.set_title(text)
                task.set_to_keep()
            task.set_due_date(due_date)
            task.set_start_date(defer_date)
            id_toselect = task.get_id()
            #############
            self.quickadd_entry.set_text('')
            # Refresh the treeview
            #self.do_refresh(toselect=id_toselect)
            for f in self.priv['quick_add_cbs']:
                f(task)

    def on_tag_treeview_button_press_event(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = treeview.get_path_at_pos(x, y)
            if pthinfo is not None:
                path, col, cellx, celly = pthinfo #pylint: disable-msg=W0612
                treeview.grab_focus()
                treeview.set_cursor(path, col, 0)
                selected_tags = self.get_selected_tags()[0]
                if len(selected_tags) > 0:
                    # Then we are looking at single, normal tag rather than
                    # the special 'All tags' or 'Tasks without tags'. We only
                    # want to popup the menu for normal tags.
                    display_in_workview_item = self.tagpopup.get_children()[1]
                    selected_tag = selected_tags[0]
                    nonworkview = selected_tag.get_attribute("nonworkview")
                    # We must invert because the tagstore has "True" for tasks
                    # that are *not* in workview, and the checkbox is set if
                    # the tag *is* shown in the workview.
                    if nonworkview == "True":
                        shown = False
                    else:
                        shown = True
                    display_in_workview_item.set_active(shown)
                    self.tagpopup.popup(None, None, None, event.button, time)
            return 1

    def on_nonworkviewtag_toggled(self, widget):
        tags = self.get_selected_tags()[0]
        nonworkview_item = self.tagpopup.get_children()[1]
        #We must inverse because the tagstore has True
        #for tasks that are not in workview (and also convert to string)
        toset = str(not nonworkview_item.get_active())
        if len(tags) > 0:
            tags[0].set_attribute("nonworkview", toset)
        if self.priv['workview']:
            self.task_modelfilter.refilter()
            self.tag_modelfilter.refilter()

    def on_task_treeview_button_press_event(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = treeview.get_path_at_pos(x, y)
            if pthinfo is not None:
                path, col, cellx, celly = pthinfo
                treeview.grab_focus()
                treeview.set_cursor(path, col, 0)
                self.taskpopup.popup(None, None, None, event.button, time)
            return 1

    def on_task_treeview_key_press_event(self, treeview, event):
        if gtk.gdk.keyval_name(event.keyval) == "Delete":
            self.on_delete_task()

    def on_closed_task_treeview_button_press_event(self, treeview, event):
        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time
            pthinfo = treeview.get_path_at_pos(x, y)
            if pthinfo is not None:
                path, col, cellx, celly = pthinfo
                treeview.grab_focus()
                treeview.set_cursor(path, col, 0)
                self.ctaskpopup.popup(None, None, None, event.button, time)
            return 1

    def on_closed_task_treeview_key_press_event(self, treeview, event):
        if gtk.gdk.keyval_name(event.keyval) == "Delete":
            self.on_delete_task()

    def on_add_task(self, widget, status=None):
        tags, notagonly = self.get_selected_tags()
        task = self.req.new_task(tags=tags, newtask=True)
        uid = task.get_id()
        if status:
            task.set_status(status)
        self.open_task(uid,thisisnew=True)

    def on_add_subtask(self, widget):
        uid = self.get_selected_task()
        if uid:
            zetask = self.req.get_task(uid)
            tags   = zetask.get_tags()
            task   = self.req.new_task(tags=tags, newtask=True)
            task.add_parent(uid)
            zetask.add_subtask(task.get_id())
            self.open_task(task.get_id(),thisisnew=True)
            #self.do_refresh()

    def on_edit_active_task(self, widget, row=None, col=None):
        tid = self.get_selected_task()
        if tid:
            self.open_task(tid)

    def on_edit_done_task(self, widget, row=None, col=None):
        tid = self.get_selected_task(self.ctask_tv)
        if tid:
            self.open_task(tid)

#    def on_edit_note(self, widget, row=None, col=None):
#        tid = self.get_selected_task(self.note_tview)
#        if tid:
#            self.open_task(tid)

    def on_delete_confirm(self, widget):
        """if we pass a tid as a parameter, we delete directly
        otherwise, we will look which tid is selected"""
        self.req.delete_task(self.tid_todelete)
        if self.tid_todelete in self.opened_task:
            self.opened_task[self.tid_todelete].close()
        self.tid_todelete = None
        if self.refresh_lock.acquire(False):
            gobject.idle_add(self.general_refresh)

    def on_delete_task(self, widget=None, tid=None):
        #If we don't have a parameter, then take the selection in the treeview
        if not tid:
            #tid_to_delete is a [project,task] tuple
            self.tid_todelete = self.get_selected_task()
        else:
            self.tid_todelete = tid
        #We must at least have something to delete !
        if self.tid_todelete:
            label = self.builder.get_object("label1") 
            label_text = label.get_text()
            label_text = label_text[0:label_text.find(":") + 1]
            # I find the tasks that are going to be deleted
            titles = self.get_task_and_subtask_titles(self.tid_todelete)
            label.set_text("%s %s." % (label_text, titles))
            delete_dialog = self.builder.get_object("confirm_delete")
            delete_dialog.run()
            delete_dialog.hide()
            #has the task been deleted ?
            return not self.tid_todelete
        else:
            return False

    def on_mark_as_done(self, widget):
        uid = self.get_selected_task()
        if uid:
            zetask = self.req.get_task(uid)
            status = zetask.get_status()
            if status == Task.STA_DONE:
                zetask.set_status(Task.STA_ACTIVE)
            else:
                zetask.set_status(Task.STA_DONE)
            if self.refresh_lock.acquire(False):
                gobject.idle_add(self.general_refresh)

    def on_dismiss_task(self, widget):
        uid = self.get_selected_task()
        if uid:
            zetask = self.req.get_task(uid)
            status = zetask.get_status()
            if status == "Dismiss":
                zetask.set_status("Active")
            else:
                zetask.set_status("Dismiss")
            if self.refresh_lock.acquire(False):
                gobject.idle_add(self.general_refresh)
    
    def on_select_tag(self, widget, row=None, col=None):
        #When you clic on a tag, you want to unselect the tasks
        self.task_tv.get_selection().unselect_all()
        self.ctask_tv.get_selection().unselect_all()
        task_model = self.task_tv.get_model()
        task_model.foreach(self.update_collapsed_row, None)
        self.task_modelfilter.refilter()
        self._update_window_title()

    def on_taskdone_cursor_changed(self, selection=None):
        """Called when selection changes in closed task view.

        Changes the way the selected task is displayed.
        """
        #We unselect all in the active task view
        #Only if something is selected in the closed task list
        #And we change the status of the Done/dismiss button
        self.donebutton.set_icon_name("gtg-task-done")
        self.dismissbutton.set_icon_name("gtg-task-dismiss")
        if selection.count_selected_rows() > 0:
            tid = self.get_selected_task(self.ctask_tv)
            task = self.req.get_task(tid)
            self.task_tv.get_selection().unselect_all()
#            self.note_tview.get_selection().unselect_all()
            if task.get_status() == "Dismiss":
                self.builder.get_object(
                    "ctcm_mark_as_not_done").set_sensitive(False)
                self.builder.get_object("ctcm_undismiss").set_sensitive(True)
                self.dismissbutton.set_label(GnomeConfig.MARK_UNDISMISS)
                self.donebutton.set_label(GnomeConfig.MARK_DONE)
                self.donebutton.set_tooltip_text(GnomeConfig.MARK_DONE_TOOLTIP)
                self.dismissbutton.set_icon_name("gtg-task-undismiss")
                self.dismissbutton.set_tooltip_text(
                    GnomeConfig.MARK_UNDISMISS_TOOLTIP)
            else:
                self.builder.get_object(
                    "ctcm_mark_as_not_done").set_sensitive(True)
                self.builder.get_object(
                    "ctcm_undismiss").set_sensitive(False)
                self.donebutton.set_label(GnomeConfig.MARK_UNDONE)
                self.donebutton.set_tooltip_text(
                    GnomeConfig.MARK_UNDONE_TOOLTIP)
                self.dismissbutton.set_label(GnomeConfig.MARK_DISMISS)
                self.dismissbutton.set_tooltip_text(
                    GnomeConfig.MARK_DISMISS_TOOLTIP)
                self.donebutton.set_icon_name("gtg-task-undone")

    def on_task_cursor_changed(self, selection=None):
        """Called when selection changes in the active task view.

        Changes the way the selected task is displayed.
        """
        #We unselect all in the closed task view
        #Only if something is selected in the active task list
        self.donebutton.set_icon_name("gtg-task-done")
        self.dismissbutton.set_icon_name("gtg-task-dismiss")
        if selection.count_selected_rows() > 0:
            self.ctask_tv.get_selection().unselect_all()
#            self.note_tview.get_selection().unselect_all()
            self.donebutton.set_label(GnomeConfig.MARK_DONE)
            self.donebutton.set_tooltip_text(GnomeConfig.MARK_DONE_TOOLTIP)
            self.dismissbutton.set_label(GnomeConfig.MARK_DISMISS)

#    def on_note_cursor_changed(self, selection=None):
#        #We unselect all in the closed task view
#        #Only if something is selected in the active task list
#        if selection.count_selected_rows() > 0:
#            self.ctask_tv.get_selection().unselect_all()
#            self.task_tv.get_selection().unselect_all()
    
    def on_pluginmanager_activate(self, widget):
        if self.pm:
            self.pm.present()
        else:
            self.pm = PluginManager(self.window, self.plugins, self.pengine, self.p_apis)

    def on_close(self, widget=None):
        """Closing the window."""
        #Saving is now done in main.py
        self.on_delete(None, None)
        gtk.main_quit()

    def on_task_added(self, sender, tid):
        if self.logger:
            self.logger.debug("Add task with ID: %s" % tid)
        self.task_tree_model.add_task(tid)
        #no need to do more as task_modified will be called anyway
        
    def on_task_deleted(self, sender, tid):
        if self.logger:
            self.logger.debug("Delete task with ID: %s" % tid)
        self.task_tree_model.remove_task(tid)
        self.tags_tv.refresh()
        self._update_window_title()
        #if the modified task is active, we have to refresh everything
        #to avoid some odd stuffs when loading
        if self.refresh_lock.acquire(False):
            gobject.idle_add(self.general_refresh)
                        
    def on_task_modified(self, sender, tid):
        if self.logger:
            self.logger.debug("Modify task with ID: %s" % tid)
        self.task_tree_model.update_task(tid)
        if self.task_tree_model.remove_task(tid):
            self.task_tree_model.add_task(tid)
        self.tag_model.update_tags_for_task(tid)
        self.tags_tv.refresh()
        #We also refresh the opened windows for that tasks,
        #his children and his parents
        #It might be faster to refresh every opened editor
        tlist = [tid]
        task = self.req.get_task(tid)
        tlist += task.get_parents()
        tlist += task.get_subtask_tids()
        for uid in tlist:
            if self.opened_task.has_key(uid):
                self.opened_task[uid].refresh_editor(refreshtext=True)
        #if the modified task is active, we have to refresh everything
        #to avoid some odd stuffs when loading
        if task.get_status() == "Active" :
            if self.refresh_lock.acquire(False):
                gobject.idle_add(self.general_refresh)

    def on_export(self, widget):
        #Generating lists
        self.export_template_paths = [xdg_config_home + "/gtg/export/",
                    os.path.dirname(os.path.abspath(__file__)) + "/export/"]
        for dir in self.export_template_paths: 
            if os.path.exists(dir):
                template_list = filter(lambda str: str.startswith("template_"),
                                  os.listdir(dir))
        #Creating combo-boxes
        self.export_combo_decorator(self.export_combo_templ, template_list)
        self.export_dialog.show_all()

    def on_export_cancel(self, widget = None, data = None):
        self.export_dialog.hide()
        return True

    def on_export_combo_changed(self, widget = None):
        if self.export_check_template():
            image_path = os.path.dirname(self.export_template_path)
            image_path = image_path + '/' + os.path.basename(\
                 self.export_template_path).replace("template_","thumbnail_")
            if  os.path.isfile(image_path):
                pixbuf = gtk.gdk.pixbuf_new_from_file(image_path)
                [w,h] = self.export_image.get_size_request()
                pixbuf = pixbuf.scale_simple(w, h, gtk.gdk.INTERP_BILINEAR)
                self.export_image.set_from_pixbuf(pixbuf)
            else:
                self.export_image.clear()

    def export_check_template(self):
        #Check template file 
        #NOTE: if two templates have the same name, the user provided one takes
        #      precedence over ours
        supposed_template = self.combo_get_text(self.export_combo_templ)
        if supposed_template == None:
            return False
        self.export_combo_active = self.export_combo_templ.get_active()
        supposed_template_paths = map (lambda x: x + supposed_template,
                                       self.export_template_paths)
        template_paths = filter (lambda x: os.path.isfile(x),
                                 supposed_template_paths)
        if len(template_paths) >0:
            template_path = template_paths[0]
        else:
            return False
        self.export_template_path = template_path
        self.export_template_filename = supposed_template
        return True

    def export_tree_visit(self, model, task_iter):
        class TaskStr:
            def __init__(self,
                         title,
                         text,
                         subtasks,
                         status,
                         modified,
                         due_date,
                         closed_date,
                         start_date,
                         days_left,
                         tags
                        ):
                self.title         = title
                self.text          = text
                self.subtasks      = subtasks
                self.status        = status
                self.modified      = modified
                self.due_date      = due_date
                self.closed_date   = closed_date
                self.start_date    = start_date
                self.days_left     = days_left
                self.tags          = tags
            has_title         = property(lambda s: s.title       != "")
            has_text          = property(lambda s: s.text        != "")
            has_subtasks      = property(lambda s: s.subtasks    != [])
            has_status        = property(lambda s: s.status      != "")
            has_modified      = property(lambda s: s.modified    != "")
            has_due_date      = property(lambda s: s.due_date    != "")
            has_closed_date   = property(lambda s: s.closed_date != "")
            has_start_date    = property(lambda s: s.start_date  != "")
            has_days_left     = property(lambda s: s.days_left   != "")
            has_tags          = property(lambda s: s.tags        != [])
        tasks_str = []
        while task_iter:
            task = model.get_value(task_iter, tasktree.COL_OBJ)
            task_str = TaskStr(task.get_title(),
                               str(task.get_text()),
                               [],
                               task.get_status(),
                               str(task.get_modified()),
                               str(task.get_due_date()),
                               str(task.get_start_date()),
                               str(task.get_days_left()),
                               str(task.get_closed_date()),
                               map(lambda t: t.get_name(), task.get_tags()))
            if model.iter_has_child(task_iter):
                task_str.subtasks = \
                    self.export_tree_visit(model, model.iter_children(task_iter))
            tasks_str.append(task_str)
            task_iter = model.iter_next(task_iter)
        return tasks_str

    def export_generate(self):
        #Template loading and cutting
        model = self.task_modelsort
        tasks_str = self.export_tree_visit(model, model.get_iter_first())
        self.export_document = str(Template (file = self.export_template_path,
                      searchList = [{ 'tasks': tasks_str}]))
        return True

    def export_execute_with_ui(self):
        call = [(self.export_check_template, _("Template not found")),\
                (self.export_generate      , _("Can't load the template file") )]
        for step in call:
            if not step[0]():
                dialog = gtk.MessageDialog(parent = \
                     self.export_dialog,
                     flags = gtk.DIALOG_DESTROY_WITH_PARENT,
                     type = gtk.MESSAGE_ERROR,
                     buttons=gtk.BUTTONS_OK,
                     message_format=step[1])
                dialog.run() 
                dialog.destroy()
                return False
        return True

    def export_save_file(self, output_path):
        with open(output_path, 'w+b') as file:
            file.write(self.export_document)

    def on_export_open(self, widget = None):
        if not self.export_execute_with_ui():
            return
        path = '/tmp/' + self.export_template_filename
        self.export_save_file(path)
        subprocess.Popen(['xdg-open', path])

    def on_export_save(self, widget = None):
        if not self.export_execute_with_ui():
            return
        chooser = gtk.FileChooserDialog(\
                title = _("Choose where to save your list"),
                parent = self.export_dialog,
                action = gtk.FILE_CHOOSER_ACTION_SAVE,
                buttons = (gtk.STOCK_CANCEL,
                           gtk.RESPONSE_CANCEL,
                           gtk.STOCK_SAVE,
                           gtk.RESPONSE_OK))
        chooser.set_do_overwrite_confirmation(True)
        desktop_dir = self.get_user_dir("XDG_DESKTOP_DIR")
        #NOTE: using ./scripts/debug.sh, it doesn't detect the Desktop
        # dir, as the XDG directories are changed. That is why during 
        # debug it defaults to the Home directory ~~Invernizzi~~
        if desktop_dir != None and os.path.exists(desktop_dir):
            chooser.set_current_folder(desktop_dir)
        else:
            chooser.set_current_folder(os.environ['HOME'])
        chooser.set_default_response(gtk.RESPONSE_OK)
        response = chooser.run()
        filename = chooser.get_filename()
        chooser.destroy()
        if response == gtk.RESPONSE_OK and filename != None:
            self.export_save_file(filename)
        self.on_export_cancel()

    def general_refresh(self):
        if self.logger:
            self.logger.debug("Trigger refresh on taskbrowser.")
        self.tag_modelfilter.refilter()
        self.task_modelfilter.refilter()
#        self.tags_tv.refresh()
        self._update_window_title()
        self.refresh_lock.release()

### PUBLIC METHODS ############################################################
#
    def get_selected_task(self, tv=None):
        """Return the 'uid' of the selected task

        :param tv: The tree view to find the selected task in. Defaults to
            the task_tview.
        """
        uid = None
        if not tv:
            tview = self.task_tv
        else:
            tview = tv
        # Get the selection in the gtk.TreeView
        selection = tview.get_selection()
        #If we don't have anything and no tview specified
        #Let's have a look in the closed task view
        if selection and selection.count_selected_rows() <= 0 and not tv:
            tview = self.ctask_tv
            selection = tview.get_selection()
        #Then in the notes pane
#        if selection and selection.count_selected_rows() <= 0 and not tv:
#            tview = self.note_tview
#            selection = tview.get_selection()
        # Get the selection iter
        if selection:
            model, selection_iter = selection.get_selected()
            if selection_iter:
                ts  = tview.get_model()
                uid = ts.get_value(selection_iter, tasktree.COL_TID)
        return uid

    def get_selected_tags(self):
        t_selected = self.tags_tv.get_selection()
        model      = self.tags_tv.get_model()
        t_iter = None
        if t_selected:
            tmodel, t_iter = t_selected.get_selected()
        notag_only = False
        tag = []
        if t_iter:
            selected = model.get_value(t_iter, tagtree.COL_OBJ)
            special  = selected.get_attribute("special")
            if special == "all":
                tag = []
                selected = None
            #notag means we want to display only tasks without any tag
            if special == "notag":
                notag_only = True
            if not notag_only and selected:
                tag.append(selected)
        #If no selection, we display all
        return tag, notag_only

    def get_n_active_tasks(self):
        count = 0
        model = self.task_modelsort
        c = model.get_iter_first()
        while c:
            count = count + 1 + self._count_subtask(model, c)
            c     = model.iter_next(c)
        return count


### MAIN ######################################################################
#
    def main(self):

        # Here we will define the main TaskList interface
        gobject.threads_init()

        # Watch for selections in the treeview
        selection = self.task_tv.get_selection()
        closed_selection = self.ctask_tv.get_selection()
        #note_selection = self.note_tview.get_selection()
        selection.connect("changed", self.on_task_cursor_changed)
        closed_selection.connect("changed", self.on_taskdone_cursor_changed)
        #note_selection.connect("changed", self.on_note_cursor_changed)

        # Restore state from config
        self.restore_state_from_conf()
        self.window.show()
        gtk.main()
        return 0
