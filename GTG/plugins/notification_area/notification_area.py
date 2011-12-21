# -*- coding: utf-8 -*-
# Copyright (c) 2009 - Paulo Cabido <paulo.cabido@gmail.com>
#                    - Luca Invernizzi <invernizzi.l@gmail.com> 
#                    - Izidor Matušov <izidor.matusov@gmail.com>
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

import os
import gtk
try:
    import appindicator
except:
    pass

from GTG                   import _, DATA_DIR
from GTG.tools.borg        import Borg
from GTG.tools.sorted_dict import SortedDict

class NotificationArea:
    """
    Plugin that display a notification area widget or an indicator
    to quickly access tasks.
    """

    DEFAULT_PREFERENCES = {"start_minimized": False}
    PLUGIN_NAME = "notification_area"
    MAX_TITLE_LEN = 30

    class TheIndicator(Borg):
        """
        Application indicator can be instantiated only once. The
        plugin api, when toggling the activation state of a plugin,
        instantiates different objects from the plugin class. Therefore,
        we need to keep a reference to the indicator object. This class
        does that.
        """
        def __init__(self):
            super(NotificationArea.TheIndicator, self).__init__()
            if not hasattr(self, "_indicator"):
                try:
                    self._indicator = appindicator.Indicator( \
                                  "gtg",
                                  "indicator-messages",
                                   appindicator.CATEGORY_APPLICATION_STATUS)
                    self._indicator.set_icon("gtg")
                except:
                    self._indicator = None

        def get_indicator(self):
            return self._indicator

    def __init__(self):
        self.__indicator = NotificationArea.TheIndicator().get_indicator()
        self.__browser_handler = None

    def activate(self, plugin_api):
        self.__plugin_api = plugin_api
        self.__view_manager = plugin_api.get_view_manager()
        self.__requester = plugin_api.get_requester()
        #Tasks_in_menu will hold the menu_items in the menu, to quickly access
        #them given the task id. Contains tuple of this format: (title, key,
        # gtk.MenuItem)
        self.__tasks_in_menu = SortedDict(key_position = 1, sort_position = 0)
        self.__init_gtk()
        self.__connect_to_tree()
        #Load the preferences
        self.preference_dialog_init()
        self.preferences_load()

        # When no windows (browser or text editors) are shown, it tries to quit
        # With hidden browser and closing the only single text editor, 
        # GTG would quit no matter what
        self.__view_manager.set_daemon_mode(True)

        # Don't quit GTG after closing browser
        self.__set_browser_close_callback(self.__on_browser_minimize)
        if self.preferences["start_minimized"]:
            self.__view_manager.start_browser_hidden()

    def deactivate(self, plugin_api):
        if self.__indicator:
            self.__indicator.set_status(appindicator.STATUS_PASSIVE)
        else:
            self.__status_icon.set_visible(False)

        # Allow to close browser after deactivation
        self.__set_browser_close_callback(None)

        # Allow closing GTG after the last window
        self.__view_manager.set_daemon_mode(True)

## Helper methods ##############################################################

    def __init_gtk(self):
        self.__menu = gtk.Menu()
        #view in main window checkbox
        view_browser_checkbox = gtk.CheckMenuItem(_("_View Main Window"))
        view_browser_checkbox.set_active(self.__view_manager.get_browser( \
                                                            ).is_shown())
        self.__signal_handler = view_browser_checkbox.connect('activate',
                                                       self.__toggle_browser)
        self.__view_manager.get_browser().connect('visibility-toggled',
                                                self.__on_browser_toggled,
                                                view_browser_checkbox)
        self.__menu.append(view_browser_checkbox)
        self.checkbox = view_browser_checkbox
        #add "new task"
        menuItem = gtk.ImageMenuItem(gtk.STOCK_ADD)
        menuItem.get_children()[0].set_label(_('Add _New Task'))
        menuItem.connect('activate', self.__open_task)
        self.__menu.append(menuItem)
        #quit item
        menuItem = gtk.ImageMenuItem(gtk.STOCK_QUIT)
        menuItem.connect('activate', self.__view_manager.close_browser)
        self.__menu.append(menuItem)
        self.__menu.show_all()
        #separator (it's intended to be after show_all)
        self.__task_separator = gtk.SeparatorMenuItem()
        self.__task_separator.show()
        self.__menu.append(self.__task_separator)
        self.__menu_top_length = len(self.__menu)

        if self.__indicator:
            self.__indicator.set_menu(self.__menu)
            self.__indicator.set_status(appindicator.STATUS_ACTIVE)
        else:
            print "ELSE?"
#FIXME TODO there should be not GTG
            icon = gtk.gdk.pixbuf_new_from_file_at_size(DATA_DIR + \
                                "/icons/hicolor/16x16/apps/gtg.png", 16, 16)
            self.status_icon = gtk.status_icon_new_from_pixbuf(icon)
            self.status_icon.set_tooltip("Getting Things Gnome!")
            self.status_icon.set_visible(True)
            self.status_icon.connect('activate', self.__toggle_browser)
            self.status_icon.connect('popup-menu', \
                                     self.__on_icon_popup, \
                                     self.__menu)

    def __open_task(self, widget, task_id = None):
        """
        Opens a task in the TaskEditor, if it's not currently opened.
        If task_id is None, it creates a new task and opens it
        """
        if task_id == None:
            task_id = self.__requester.new_task().get_id()
            new_task = True
        else:
            new_task = False

        self.__view_manager.open_task(task_id, thisisnew=new_task)

    def __connect_to_tree(self):
        self.__tree = self.__requester.get_tasks_tree()
        # Request a new view so we do not influence anybody
        self.__tree = self.__tree.get_basetree().get_viewtree(refresh=False)
        self.__tree.apply_filter('workview')
        self.__tree.register_cllbck("node-added-inview", self.__on_task_added)
        self.__tree.register_cllbck("node-deleted-inview", self.__on_task_deleted)
        self.__tree.register_cllbck("node-modified-inview", self.__on_task_added)

        #Flushing all tasks, as the plugin may have been started after GTG
        def visit_tree(tree, nodes, fun):
            for node in nodes:
                tid = node.get_id()
                if tree.is_displayed(tid):
                    fun(tid)
                    if node.has_child():
                        children = [self.__tree.get_node(c) \
                                    for c in node.get_children()]
                        visit_tree(tree, children, fun)
        virtual_root = self.__tree.get_root()
        visit_tree(self.__tree,
                   [self.__tree.get_node(c) \
                            for c in virtual_root.get_children()],
                   lambda t: self.__on_task_added(t, None))

    def __on_task_added(self, tid, path):
        self.__task_separator.show()
        task = self.__requester.get_task(tid)
        #ellipsis of the title
        title = self.__create_short_title(task.get_title())
        try:
            #if it's already in the menu, remove it (to reinsert in a sorted
            # way)
            menu_item = self.__tasks_in_menu.pop_by_key(tid)[2]
            self.__menu.remove(menu_item)
        except:
            pass
        #creating the menu item
        menu_item = gtk.MenuItem(title,False)
        menu_item.connect('activate', self.__open_task, tid)
        menu_item.show()
        position = self.__tasks_in_menu.sorted_insert((title, tid, menu_item))
        self.__menu.insert(menu_item, position + self.__menu_top_length)
        if self.__indicator:
            self.__indicator.set_menu(self.__menu)

    def __create_short_title(self, title):
        # Underscores must be escaped to avoid to be ignored (or, optionally,
        # treated like accelerators ~~ Invernizzi
        title =title.replace("_", "__")
        short_title = title[0 : self.MAX_TITLE_LEN]
        if len(title) > self.MAX_TITLE_LEN:
            short_title = short_title.strip() + "..."
        return short_title

    def __on_task_deleted(self, tid, path):
        try:
            menu_item = self.__tasks_in_menu.pop_by_key(tid)[2]
            self.__menu.remove(menu_item)
        except:
            return
        #if the dynamic menu is empty, remove the separator
        if not self.__tasks_in_menu:
            self.__task_separator.hide()

    def __on_icon_popup(self, icon, button, timestamp, menu=None):
        if not self.__indicator:
            menu.popup(None, None, gtk.status_icon_position_menu, \
                       button, timestamp, icon)

### Preferences methods #######################################################

    def preferences_load(self):
        data = self.__plugin_api.load_configuration_object(self.PLUGIN_NAME,
                                                         "preferences")
        if not data or not isinstance(data, dict):
            self.preferences = self.DEFAULT_PREFERENCES
        else:
            self.preferences = data

    def preferences_store(self):
        self.__plugin_api.save_configuration_object(self.PLUGIN_NAME,
                                                  "preferences",
                                                  self.preferences)
    def is_configurable(self):
        """A configurable plugin should have this method and return True"""
        return True

    def preference_dialog_init(self):
        self.builder = gtk.Builder()
        self.builder.add_from_file(os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "notification_area.ui"))
        self.preferences_dialog = self.builder.get_object("preferences_dialog")
        self.chbox_minimized = self.builder.get_object("pref_chbox_minimized")
        SIGNAL_CONNECTIONS_DIC = {
            "on_preferences_dialog_delete_event":
                self.on_preferences_cancel,
            "on_btn_preferences_cancel_clicked":
                self.on_preferences_cancel,
            "on_btn_preferences_ok_clicked":
                self.on_preferences_ok
        }
        self.builder.connect_signals(SIGNAL_CONNECTIONS_DIC)

    def configure_dialog(self, manager_dialog):
        self.chbox_minimized.set_active(self.preferences["start_minimized"])
        self.preferences_dialog.show_all()
        self.preferences_dialog.set_transient_for(manager_dialog)

    def on_preferences_cancel(self, widget = None, data = None):
        self.preferences_dialog.hide()
        return True

    def on_preferences_ok(self, widget = None, data = None):
        self.preferences["start_minimized"] = self.chbox_minimized.get_active()
        self.preferences_store()
        self.preferences_dialog.hide()

### Browser methods ###########################################################

    def __on_browser_toggled(self, sender, checkbox):
        checkbox.disconnect(self.__signal_handler)
        is_shown = self.__view_manager.get_browser().is_shown()
        checkbox.set_active(is_shown)
        self.__signal_handler = checkbox.connect('activate',
                                               self.__toggle_browser)

    def __on_browser_minimize(self, widget = None, plugin_api = None):
        self.__view_manager.hide_browser()
        return True

    def __toggle_browser(self, sender = None, data = None):
        if self.__plugin_api.get_ui().is_shown():
            self.__plugin_api.get_view_manager().hide_browser()
        else:
            self.__plugin_api.get_view_manager().show_browser()

    def __set_browser_close_callback(self, method):
        """ Set a callback for browser's close event. If method is None,
        unset the previous callback """

        browser = self.__view_manager.get_browser()

        if self.__browser_handler is not None:
            browser.window.disconnect(self.__browser_handler)

        if method is not None:
            self.__browser_handler = browser.window.connect(
                "delete-event", method)
