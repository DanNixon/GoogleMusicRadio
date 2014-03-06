#!/usr/bin/python

## Google Play Music client script for Rasp. Pi radio
## Copyright: Dan Nixon 2012-13
## dan-nixon.com
## Version: 0.4
## Date: 04/03/2014

import thread, time, random, string
from gmusicapi import Mobileclient
import RPi.GPIO as gpio
import smbus
import serial
import gobject, glib
import gst

#__MusicClient__ = None
#__MediaPlayer__ = None
#__VolumeMan__ = None
#__LCDMan__ = None
#__LastFm__ = None
#__LCDMenuMan__ = None
__SerialPort__ = None

class switch(object):
	def __init__(self, value):
		self.value = value
		self.fall = False

	def __iter__(self):
		yield self.match
		raise StopIteration
    
	def match(self, *args):
		if self.fall or not args:
			return True
		elif self.value in args:
			self.fall = True
			return True
		else:
			return False

class GPMClient(object):
	all_songs_album_title = "All Songs"
	thumbs_up_playlist_name = "Thumbs Up"

	def __init__(self, email, password, device_id):
		self.__api = Mobileclient()
		self.logged_in = False
		self.__device_id = device_id

		attempts = 0
		while not self.logged_in and attempts < 3:
			self.logged_in = self.__api.login(email, password)
			attempts += 1

		self.all_tracks = dict()
		self.playlists = dict()
		self.library = dict()

	def __del__(self):
		self.__api.logout()

	def update_local_lib(self):
		print "Getting all library tracks"
		songs = self.__api.get_all_songs()
		self.playlists[self.thumbs_up_playlist_name] = list()

		#	Get main library
		print "Processing library tracks"
		song_map = dict()	
		for song in songs:
			if "rating" in song and song["rating"] == "5":
				self.playlists[self.thumbs_up_playlist_name].append(song)

			song_id = song["id"]
			song_artist = song["artist"]
			song_album = song["album"]

			song_map[song_id] = song

			if song_artist == "":
				song_artist = "Unknown Artist"

			if song_album == "":
				song_album = "Unknown Album"

			if not (song_artist in self.library):
				self.library[song_artist] = dict()
				self.library[song_artist][self.all_songs_album_title] = list()

			if not (song_album in self.library[song_artist]):
				self.library[song_artist][song_album] = list()

			self.library[song_artist][song_album].append(song)
			self.library[song_artist][self.all_songs_album_title].append(song)

		# Sort albums by track number
		print "Sorting library tracks"
		for artist in self.library.keys():
			for album in self.library[artist].keys():
				if album == self.all_songs_album_title:
					sorted_album = sorted(self.library[artist][album], key=lambda k: k['title'])
				else:
					sorted_album = sorted(self.library[artist][album], key=lambda k: k['trackNumber'])
				self.library[artist][album] = sorted_album

		#	Get all playlists
		print "Getting user playlists"
		plists = self.__api.get_all_user_playlist_contents()
		for plist in plists:
			plist_name = plist["name"]
			self.playlists[plist_name] = list()
			for track in plist["tracks"]:
				song = song_map[track["trackId"]]
				self.playlists[plist_name].append(song)

	def get_stream_url(self, song):
		return self.__api.get_stream_url(song["id"], self.__device_id)

	def rate_song(self, song, rating):
		try:
			song["rating"] = rating
			song_list = [song]
			self.__api.change_song_metadata(song_list)
			print "Gave a Thumbs Up to {0} by {1} on Google Play.".format(song["title"].encode("utf-8"), song["artist"].encode("utf-8"))
		except:
			print "Error giving a Thumbs Up on Google Play."

class MediaPlayer(object):
	def __init__(self):
		self.__player = None
			
		self.now_playing_song = None
		self.queue = list()
		self.queue_index = -1

		self.random = False
		self.repeat = True

		thread.start_new_thread(self.player_thread, ())
	
	def __del__(self):
		self.now_playing_song = None
		self.__player.set_state(gst.STATE_NULL)
	
	def player_thread(self):
		if self.__player == None:
			print "Creating a new GStreamer player..."
			self.__player = gst.element_factory_make("playbin2", "player")
			self.__player.set_state(gst.STATE_NULL)
			bus = self.__player.get_bus()
			bus.add_signal_watch()
			bus.connect("message", self.handle_song_end)
			glib.MainLoop().run()
		else:
			print "Player already exists!"
	
	def get_state(self):
		return self.__player.get_state()[1]

	def handle_song_end(self, bus, message):
		if message.type == gst.MESSAGE_EOS:
			__LastFm__.scrobble(self.now_playing_song)
			self.stop()
			print "Finished playing last song"
			self.play_next_in_queue()
	
	def clear_queue(self):
		self.queue = list()
		self.queue_index = -1
		__LCDMenuMan__.update_queue()

	def play(self, song):
		print "Song: ", song
		song_url = __MusicClient__.get_stream_url(song)
		print "Got song URL: ", song_url
		try:
			print "Playing song."
			if not __VolumeMan__.is_mute:
				__VolumeMan__.set_amp_power(True)
			self.__player.set_property("uri", song_url)
			self.__player.set_state(gst.STATE_PLAYING)
			self.now_playing_song = song
			time.sleep(0.5)
			__LCDMan__.update()
		except AttributeError:
			print "Player does not yet exist!"
		__LastFm__.update_now_playing(song)

	def toggle_playback(self):
		try:
			player_state = self.__player.get_state()[1]
			if player_state == gst.STATE_PAUSED:
				print "Resuming paused playback"
				if not __VolumeMan__.is_mute:
					__VolumeMan__.set_amp_power(True)
				self.__player.set_state(gst.STATE_PLAYING)
				if __LCDMan__.lcd_base == __LCDMan__.base_playing:
					__LCDMan__.update()
			elif player_state == gst.STATE_PLAYING:
				print "Pausing playback"
				self.__player.set_state(gst.STATE_PAUSED)
				if not __VolumeMan__.is_mute:
					__VolumeMan__.set_amp_power(False)	
				if __LCDMan__.lcd_base == __LCDMan__.base_playing:
					__LCDMan__.update()
			elif player_state == gst.STATE_NULL:
				print "Nothing in player"
				self.play_next_in_queue()
				if __LCDMan__.lcd_base == __LCDMan__.base_playing:
					__LCDMan__.update()
		except AttributeError:
			print "Player does not yet exist!"

	def stop(self):
		try:
			print "Stopping playback"
			self.__player.set_state(gst.STATE_NULL)
			self.now_playing_song = None
		except AttributeError:
			print "Player does not yet exist!"

	def play_next_in_queue(self):
		print "Playing next song in queue"
		if self.random:
			self.queue_index = random.randint(0, (len(self.queue) - 1))
		else:
			self.queue_index = self.queue_index + 1
		if self.queue_index == len(self.queue):
			if self.repeat:
				self.queue_index = 0
			else:
				self.stop()
				__VolumeMan__.set_amp_power(False)
				print "The queue is empty!"
				return
		next_song = self.queue[self.queue_index]
		self.play(next_song)

	def add_to_queue(self, song):
		print "Adding song to queue. Song ID: ", song["id"]
		self.queue.append(song)
		__LCDMenuMan__.update_queue()

	def next(self):
		__LastFm__.scrobble(self.now_playing_song)
		self.stop()
		self.play_next_in_queue()

class VolumeManager(object):
	__amppwr_gpio = 24

	def __init__(self, init_vol):
		self.curr_vol = 0
		self.amp_on = False
		self.is_mute = False

		print "Setting up volume...",
		self.__bus = smbus.SMBus(1)
		gpio.setup(self.__amppwr_gpio, gpio.OUT)
		gpio.output(self.__amppwr_gpio, gpio.HIGH)
		print "done."

	def __del__(self):
		gpio.output(self.__amppwr_gpio, gpio.HIGH)

	def toggle_mute(self):
		self.is_mute = not self.is_mute
		amp_on = not self.is_mute
		self.set_amp_power(amp_on)
		if self.is_mute:
			print "Muted"
		else:
			print "Un muted"
		__LCDMan__.lcd_amp_power()

	def set_amp_power(self, on_r):
		if on_r:
			gpio.output(self.__amppwr_gpio, gpio.LOW)
		else:
			gpio.output(self.__amppwr_gpio, gpio.HIGH)
		self.amp_on = on_r
		b_vol = 64 - self.curr_vol
		time.sleep(0.25)
		self.__bus.write_byte_data(0x28, 0xAF, b_vol)
	
	def inc_vol(self):
		print "Volume++",
		if not ((self.curr_vol + 1) == 64):
			self.curr_vol += 1
			dp_vol = 64 - self.curr_vol
			self.__bus.write_byte_data(0x28, 0xAF, dp_vol)
			print "New volume: {0}".format(self.curr_vol)
		else:
			print "Max volume!"

	def dec_vol(self):
		print "Volume--",
		if not ((self.curr_vol - 1) == -1):
			self.curr_vol -= 1
			dp_vol = 64 - self.curr_vol
			self.__bus.write_byte_data(0x28, 0xAF, dp_vol)
			print "New volume: {0}".format(self.curr_vol)
		else:
			print "Min volume!"

class LCDMenuManager(object):
	def __init__(self):
		self.__lcd_cols = __LCDMan__.lcd_cols
		
		self.menu_struct = dict()
		self.menu_level = 0
		self.menu_history = list()
		self.menu_index = 0
		self.cursor_pos = 0
		self.list_pos = 0
		self.current_menu_display = list()

		self.init_struct()

	def update_queue(self):
		if not (len(__MediaPlayer__.queue) == 0):
			self.menu_struct["Queue"] = __MediaPlayer__.queue
		else:
			self.menu_struct["Queue"] = ["Queue Empty"]
	
	def init_struct(self):
		self.update_queue()
		self.menu_struct["Playlists"] = __MusicClient__.playlists
		self.menu_struct["Settings"] = ["Toggle Play Mode", "Toggle Repeat", "Clear Queue", "Toggle Scrobbling", "Reload Library"]
		self.menu_struct["Library"] = {
				'A':dict(), 'B':dict(), 'C':dict(),
				'D':dict(), 'E':dict(), 'F':dict(),
				'G':dict(), 'H':dict(), 'I':dict(),
				'J':dict(), 'K':dict(), 'L':dict(),
				'M':dict(), 'N':dict(), 'O':dict(),
				'P':dict(), 'Q':dict(), 'R':dict(),
				'S':dict(), 'T':dict(), 'U':dict(),
				'V':dict(), 'W':dict(), 'X':dict(),
				'Y':dict(), 'Z':dict(), '#':dict()}
		for artist, data in __MusicClient__.library.iteritems():
			name_letter = artist[:1].upper()
			if name_letter in string.ascii_uppercase:
				self.menu_struct["Library"][name_letter][artist] = data
			else:
				self.menu_struct["Library"]['#'][artist] = data
	
	def render_menu(self):
		for case in switch(self.menu_level):
			if case(0):
				self.current_menu_display = self.menu_struct
				break
			if case(1):
				self.current_menu_display = self.menu_struct[self.menu_history[0]]
				break
			if case(2):
				self.current_menu_display = self.menu_struct[self.menu_history[0]][self.menu_history[1]]
				break
			if case(3):
				self.current_menu_display = self.menu_struct[self.menu_history[0]][self.menu_history[1]][self.menu_history[2]]
				break
			if case(4):
				self.current_menu_display = self.menu_struct[self.menu_history[0]][self.menu_history[1]][self.menu_history[2]][self.menu_history[3]]
				break
		if type(self.current_menu_display) is dict:
			self.current_menu_display = self.current_menu_display.keys()
		try:
			if (self.menu_history[0] == "Playlists") and (self.menu_level == 1):
				print "Showing playlists, will sort for LCD"
				self.current_menu_display.sort()
			if (self.menu_history[0] == "Library") and (self.menu_level == 1):
				print "Showing artists sel, will sort for LCD"
				self.current_menu_display.sort()
			if (self.menu_history[0] == "Library") and (self.menu_level == 2):
				print "Showing artists, will sort for LCD"
				self.current_menu_display.sort()
			if (self.menu_history[0] == "Library") and (self.menu_level == 3):
				print "Showing albums, will sort for LCD"
				self.current_menu_display.sort()
		except IndexError:
			print "No Sort on Main Menu"
		b_index = 0
		for case in switch(self.cursor_pos):
			if case(0):
				b_index = self.menu_index
				break
			if case(1):
				b_index = self.menu_index - 1
				break
			if case(2):
				b_index = self.menu_index - 2
				break
			if case(3):
				b_index = self.menu_index - 3
				break
		try:
			if(b_index < 0):
				raise IndexError("Negative indexes break the menu")
			line1 = self.current_menu_display[b_index]
		except IndexError:
			line1 = ""
		try:
			line2 = self.current_menu_display[b_index + 1]
		except IndexError:
			line2 = ""
		try:
			line3 = self.current_menu_display[b_index + 2]
		except IndexError:
			line3 = ""
		try:
			line4 = self.current_menu_display[b_index + 3]
		except IndexError:
			line4 = ""
		if type(line1) is dict:
			line1 = line1['title']
		if type(line2) is dict:
			line2 = line2['title']
		if type(line3) is dict:
			line3 = line3['title']
		if type(line4) is dict:
			line4 = line4['title']
		line1 = __LCDMan__.ascii_filter(line1)
		line2 = __LCDMan__.ascii_filter(line2)
		line3 = __LCDMan__.ascii_filter(line3)
		line4 = __LCDMan__.ascii_filter(line4)
		for case in switch(self.cursor_pos):
			if case(0):
				line1 = ("{}{}".format(">", line1))[:self.__lcd_cols]
				line2 = ("{}{}".format(" ", line2))[:self.__lcd_cols]
				line3 = ("{}{}".format(" ", line3))[:self.__lcd_cols]
				line4 = ("{}{}".format(" ", line4))[:self.__lcd_cols]
				break
			if case(1):
				line1 = ("{}{}".format(" ", line1))[:self.__lcd_cols]
				line2 = ("{}{}".format(">", line2))[:self.__lcd_cols]
				line3 = ("{}{}".format(" ", line3))[:self.__lcd_cols]
				line4 = ("{}{}".format(" ", line4))[:self.__lcd_cols]
				break
			if case(2):
				line1 = ("{}{}".format(" ", line1))[:self.__lcd_cols]
				line2 = ("{}{}".format(" ", line2))[:self.__lcd_cols]
				line3 = ("{}{}".format(">", line3))[:self.__lcd_cols]
				line4 = ("{}{}".format(" ", line4))[:self.__lcd_cols]
				break
			if case(3):
				line1 = ("{}{}".format(" ", line1))[:self.__lcd_cols]
				line2 = ("{}{}".format(" ", line2))[:self.__lcd_cols]
				line3 = ("{}{}".format(" ", line3))[:self.__lcd_cols]
				line4 = ("{}{}".format(">", line4))[:self.__lcd_cols]
				break
		__LCDMan__.menu_lines = [line1, line2, line3, line4]
		print "MENU:", __LCDMan__.menu_lines
		__LCDMan__.update()
	
	def menu_up(self):
		if not (self.menu_index == 0):
			self.menu_index = self.menu_index - 1
			if self.cursor_pos == 2:
				self.cursor_pos = 1
		self.render_menu()
	
	def menu_down(self):
		if not (self.menu_index == (len(self.current_menu_display) - 1)):
			self.menu_index = self.menu_index + 1
			if not (self.cursor_pos == 2):
				self.cursor_pos = self.cursor_pos + 1
		self.render_menu()
	
	def menu_select(self):
		no_lcd_update = False
		selected_item_name = self.current_menu_display[self.menu_index]
		selected_item = None
		for case in switch(self.menu_level):
			if case(0):
				selected_item = self.menu_struct[selected_item_name]
				for case in switch(selected_item_name):
					if case("Queue"):
						print "Queue menu option selected."
						self.menu_level = 1
						if len(self.menu_struct["Queue"]) == 0:
							self.cursor_pos = 0
							self.menu_index = 0
						else:
							for case in switch(__MediaPlayer__.queue_index):
								if case(0):
									self.cursor_pos = 0
									self.menu_index = 0
									break
								if case(1):
									self.cursor_pos = 1
									self.menu_index = 1
									break
								if case():
									self.cursor_pos = 2
									self.menu_index = __MediaPlayer__.queue_index
									break
						self.menu_history.append("Queue")
						break
					if case("Library"):
						print "Library menu option selected."
						self.menu_level = 1
						self.cursor_pos = 0
						self.menu_index = 0
						self.menu_history.append("Library")
						break
					if case("Playlists"):
						print "Playlists menu option selected."
						self.menu_level = 1
						self.cursor_pos = 0
						self.menu_index = 0
						self.menu_history.append("Playlists")
						break
					if case("Settings"):
						print "Settings menu option selected."
						self.menu_level = 1
						self.cursor_pos = 0
						self.menu_index = 0
						self.menu_history.append("Settings")
						break
				break
			if case(1):
				try:
					selected_item = self.menu_struct[self.menu_history[0]][selected_item_name]
				except TypeError:
					selected_item = self.menu_struct[self.menu_history[0]][self.menu_index]
				for case in switch(self.menu_history[0]):
					if case("Settings"):
						for case in switch(selected_item_name):
							if case("Reload Library"):
								print "Reload Library menu option selected"
								__MediaPlayer__.stop()
								__VolumeMan__.set_amp_power(False)
								__LCDMan__.lcd_base = __LCDMan__.base_info
								__LCDMan__.info_lines = ["Updating local lib.", "from Google Play...", "", "Please Wait..."]
								__LCDMan__.update()
								__MusicClient__.update_local_lib()
								self.init_struct()
								break
							if case("Clear Queue"):
								print "Clear queue menu option selected"
								__MediaPlayer__.stop()
								__VolumeMan__.set_amp_power(False)
								__MediaPlayer__.clear_queue()
								__LCDMan__.lcd_clear_queue()
								no_lcd_update = True
								break
							if case("Toggle Scrobbling"):
								print "Last.fm menu option selected"
								__LastFm__.toggle_scrobbling()
								__LCDMan__.lcd_lastfm_toggle()
								no_lcd_update = True
								break
							if case("Toggle Play Mode"):
								print "Play mode menu option selected"
								__MediaPlayer__.random = not __MediaPlayer__.random
								__LCDMan__.lcd_play_mode_toggle()
								no_lcd_update = True
								break
							if case("Toggle Repeat"):
								print "Repeat menu option selected"
								__MediaPlayer__.repeat = not __MediaPlayer__.repeat
								__LCDMan__.lcd_repeat_toggle()
								no_lcd_update = True
								break
						break
					if case("Queue"):
						if not (selected_item == "Queue Empty"):
								print "On queue, a song was selected."
								__MediaPlayer__.queue_index = (self.menu_index - 1)
								__LCDMan__.lcd_base = __LCDMan__.base_playing
								__MediaPlayer__.next()
								no_lcd_update = True
						else:
							print "On queue, nothing selected (queue empty)"
						break
					if case("Library"):
						print "On Artist list, an artist letter was selected."
						self.menu_level = 2
						self.cursor_pos = 0
						self.menu_index = 0
						self.menu_history.append(selected_item_name)
						break
					if case("Playlists"):
						print "On Playlist list, a playlist was selected."
						self.menu_level = 2
						self.cursor_pos = 0
						self.menu_index = 0
						self.menu_history.append(selected_item_name)
						break
				break
			if case(2):
				try:
					selected_item = self.menu_struct[self.menu_history[0]][self.menu_history[1]][selected_item_name]
				except TypeError:
					selected_item = self.menu_struct[self.menu_history[0]][self.menu_history[1]][self.menu_index]
				for case in switch(self.menu_history[0]):
					if case("Playlists"):
						print "On a playlist, a song was selected."
						plist_songs = self.menu_struct[self.menu_history[0]][self.menu_history[1]]
						queue_len = len(__MediaPlayer__.queue)
						__MediaPlayer__.queue_index = queue_len + self.menu_index - 1
						for song in plist_songs:
							__MediaPlayer__.add_to_queue(song)
						__LCDMan__.lcd_base = __LCDMan__.base_playing
						__MediaPlayer__.next()
						no_lcd_update = True
						break
					if case("Library"):
						print "On an artist letter list, an artist was selected."
						self.menu_level = 3
						self.cursor_pos = 0
						self.menu_index = 0
						self.menu_history.append(selected_item_name)
						break
				break
			if case(3):
				print "On an artist, an album was selected."
				self.menu_level = 4
				self.cursor_pos = 0
				self.menu_index = 0
				self.menu_history.append(selected_item_name)
				break
			if case(4):
				print "On an album, a track was selected."
				album_songs = self.menu_struct[self.menu_history[0]][self.menu_history[1]][self.menu_history[2]][self.menu_history[3]]
				queue_len = len(__MediaPlayer__.queue)
				__MediaPlayer__.queue_index = queue_len + self.menu_index - 1
				for song in album_songs:
					__MediaPlayer__.add_to_queue(song)
				__LCDMan__.lcd_base = __LCDMan__.base_playing
				__MediaPlayer__.next()
				no_lcd_update = True
				break
		if not no_lcd_update:
			self.render_menu()
	
	def menu_return(self):
		if not (self.menu_level == 0):
			self.menu_level = self.menu_level - 1
			self.cursor_pos = 0
			self.menu_index = 0
			self.menu_history.pop()
			self.render_menu()

class LCDManager(object):
	lcd_cols = 20

	base_info = 0
	base_playing = 1
	base_volume = 2
	base_menu = 3
	base_loved = 4
	base_amp = 5
		
	__bl_gpio = 23
	__lcd_timeout = 60

	def __init__(self):
		self.backlight_timeout = 0
		self.lcd_base = self.base_info
		self.timeout = 0
		self.timer_run = False

		self.menu_lines = list()
		self.info_lines = list()

		gpio.setup(self.__bl_gpio, gpio.OUT)
		gpio.output(self.__bl_gpio, gpio.LOW)
		self.backlight_on = True
		self.backlight_timestart = time.time()
		thread.start_new_thread(self.backlight_manager, ())

	def __del__(self):
		gpio.output(self.__bl_gpio, gpio.HIGH)

	def ascii_filter(self, utf_str):
		result = ''
		for char in utf_str:
			if ord(char) < 128:
				result += char
			else:
				result += '?'
		return result
	
	def backlight_manager(self):
		while True:
			end_time = self.backlight_timestart + self.__lcd_timeout
			if time.time() > end_time:
				self.set_backlight(False)
			else:
				self.set_backlight(True)
	
	def set_backlight(self, bl_on):
		if not (bl_on == self.backlight_on):
			if bl_on:
				gpio.output(self.__bl_gpio, gpio.LOW)
				print "LCD backlight on"
			else:
				gpio.output(self.__bl_gpio, gpio.HIGH)
				print "LCD backlight off"
			self.backlight_on = bl_on
	
	def write_lcd(self, line1, line2, line3, line4):
		if not __SerialPort__ == None:
			if __SerialPort__.isOpen():
				__SerialPort__.write("24~") ##Arduino Change
				time.sleep(0.02)
				__SerialPort__.write("22%0%" + self.ascii_filter(line1)[:self.lcd_cols] + "~") ##Arduino Change
				time.sleep(0.02)
				__SerialPort__.write("22%1%" + self.ascii_filter(line2)[:self.lcd_cols] + "~") ##Arduino Change
				time.sleep(0.02)
				__SerialPort__.write("22%2%" + self.ascii_filter(line3)[:self.lcd_cols] + "~") ##Arduino Change
				time.sleep(0.02)
				__SerialPort__.write("22%3%" + self.ascii_filter(line4)[:self.lcd_cols] + "~") ##Arduino Change
			else:
				print "Serial port is not open!"
		else:
			print "Serial port does not exist!"
	
	def update(self):
		for case in switch(self.lcd_base):
			if case(self.base_info):
				self.write_lcd(self.info_lines[0], self.info_lines[1], self.info_lines[2], self.info_lines[3])
				break
			if case(self.base_playing):
				song = __MediaPlayer__.now_playing_song
				info_line_list = list()
				player_state = __MediaPlayer__.get_state()
				if player_state == gst.STATE_PLAYING:
					info_line_list.append("Playing   ")
				if player_state == gst.STATE_PAUSED:
					info_line_list.append("Paused    ")
				if __MediaPlayer__.random:
					info_line_list.append("Random")
				else:
					info_line_list.append("Linear")
				if not song == None:
					self.write_lcd(song["title"], song["artist"], song["album"], ''.join(info_line_list))
				else:
					self.write_lcd("No song playing.", "", "", "")
				break
			if case(self.base_volume):
				__SerialPort__.write("23%" + format(__VolumeMan__.curr_vol) + "~") ##Arduino Change
				break
			if case(self.base_menu):
				self.write_lcd(self.menu_lines[0], self.menu_lines[1], self.menu_lines[2], self.menu_lines[3])
				break
			if case(self.base_loved):
				song = __MediaPlayer__.now_playing_song
				self.write_lcd(song["title"], song["artist"], "Loved on Last.fm", "Thumbs up on Play")
				break
			if case(self.base_amp):
				if __VolumeMan__.amp_on:
					en_string = "Enabled"
				else:
					en_string = "Disabled"
				self.write_lcd("", "Internal Amplifier:", en_string, "")
				break

	def timer_thread(self):
		while self.timer_run:
			if time.time() > self.timeout:
				self.update()
				self.timer_run = False
				print "Timer end."
				return

	def init_timer(self, deltat):
		self.timeout = time.time() + deltat
		if not self.timer_run:
			self.timer_run = True
			thread.start_new_thread(self.timer_thread, ())
	
	def lcd_amp_power(self):
		base_last = self.lcd_base
		self.lcd_base = self.base_amp
		self.update()
		self.lcd_base = base_last
		self.init_timer(2)
	
	def lcd_loved(self):
		base_last = self.lcd_base
		self.lcd_base = self.base_loved
		self.update()
		self.lcd_base = base_last
		self.init_timer(2)

	def lcd_vol(self):
		base_last = self.lcd_base
		if not self.timer_run:
			self.update()
		self.lcd_base = self.base_volume
		self.update()
		self.lcd_base = base_last
		self.init_timer(3)
	
	def lcd_lastfm_toggle(self):
		self.lcd_base = __LCDMan__.base_info
		en_str = ""
		if __LastFm__.scrobbles_enabled:
			en_str = "Enabled"
		else:
			en_str = "Disabled"
		self.info_lines = ["Last.fm Scrobbling:", en_str, "", ""]
		self.update()
		self.lcd_base = __LCDMan__.base_menu
		self.init_timer(2)

	def lcd_clear_queue(self):
		self.lcd_base = __LCDMan__.base_info
		self.info_lines = ["Queue Cleared", "", "", ""]
		self.update()
		self.lcd_base = __LCDMan__.base_menu
		self.init_timer(2)
	
	def lcd_repeat_toggle(self):
		self.lcd_base = __LCDMan__.base_info
		repeat_str = ""
		if __MediaPlayer__.repeat:
			repeat_str = "Enabled"
		else:
			repeat_str = "Disabled"
		self.info_lines = ["Repeat:", repeat_str, "", ""]
		self.update()
		self.lcd_base = __LCDMan__.base_menu
		self.init_timer(2)

	def lcd_play_mode_toggle(self):
		self.lcd_base = __LCDMan__.base_info
		pmode_str = ""
		if __MediaPlayer__.random:
			pmode_str = "Random"
		else:
			pmode_str = "Linear"
		self.info_lines = ["Play Mode:", pmode_str, "", ""]
		self.update()
		self.lcd_base = __LCDMan__.base_menu
		self.init_timer(2)

class LastfmScrobbler(object):
	def __init__(self, username, password, use):
		self.__api_key = "3b918147d7533ddb46cbf8c90c7c4b63"
		self.__api_secret = "feb61d4de652b7223ab2341a4e436668"

		self.__session = None

		if use:
			import pylast
			password_hash = pylast.md5(password)
			self.__session = pylast.LastFMNetwork(
					api_key = self.__api_key, api_secret = self.__api_secret,
					username = username, password_hash = password_hash)

		self.enabled = use
		self.scrobbles_enabled = use

	def toggle_scrobbling(self):
		self.scrobbles_enabled = not self.scrobbles_enabled

	def love_song(self, song):
		if not song == None and self.enabled:
			print "Loving {0} by {1} on Last.fm.".format(
					song["title"].encode("utf-8"), song["artist"].encode("utf-8"))
			thread.start_new_thread(self.__love, (song,))
		else:
			print "No song playing or Last.fm disabled."

	def __love(self, song):
		title = song['title']
		artist = song['artist']
		if artist == "":
			artist = "Unknown Artist"
		try:
			track = self.__session.get_track(artist, title)
			track.love()
		except:
			pass

	def update_now_playing(self, song):
		if not song == None and self.enabled:
			thread.start_new_thread(self.__now_playing, (song,))

	def __now_playing(self, song):
		title = song['title']
		artist = song['artist']
		if artist == "":
			artist = "Unknown Artist"
		try:
			self.__session.update_now_playing(artist, title)
		except:
			pass

	def scrobble(self, song):
		if not song == None and self.enabled:
			thread.start_new_thread(self.__scrobble, (song,))

	def __scrobble(self, song):
		title = song['title']
		artist = song['artist']
		if artist == "":
			artist = "Unknown Artist"
		try:
			self.__session.scrobble(artist, title, int(time.time()))
		except:
			pass
	
def serial_handler():
	time.sleep(0.01)
	data = __SerialPort__.read(2)
	__LCDMan__.backlight_timestart = time.time()
	player_state = __MediaPlayer__.get_state()
	for case in switch(data): ##Arduino Change
		if case("11"):
			print "Stop button pressed."
			__MediaPlayer__.stop()
			__VolumeMan__.set_amp_power(False)
			__LCDMan__.lcd_base = __LCDMan__.base_menu
			__LCDMan__.update()
			break
		if case("12"):
			print "Play button pressed."
			__MediaPlayer__.toggle_playback()
			break
		if case("10"):
			print "Next button pressed."
			__MediaPlayer__.next()
			break
		if case("20"):
			print "Love pressed."
			if player_state == gst.STATE_PLAYING or player_state == gst.STATE_PAUSED:
				__LCDMan__.lcd_loved()
				__LastFm__.love_song(__MediaPlayer__.now_playing_song)
				__MusicClient__.rate_song(__MediaPlayer__.now_playing_song, 5)
			break
		if case("19"):
			print "Display pressed."
			for case in switch(__LCDMan__.lcd_base):
				if case(__LCDMan__.base_menu):
					if player_state == gst.STATE_PLAYING or player_state == gst.STATE_PAUSED:
						__LCDMan__.lcd_base = __LCDMan__.base_playing
						__LCDMan__.update()
					break
				if case(__LCDMan__.base_playing):
					__LCDMan__.lcd_base = __LCDMan__.base_menu
					__LCDMan__.update()
					break
			break
		if case("13"):
			print "Back pressed."
			if __LCDMan__.lcd_base == __LCDMan__.base_menu:
				__LCDMenuMan__.menu_return()
			break
		if case("15"):
			print "Volume up pressed."
			__VolumeMan__.inc_vol()
			__LCDMan__.lcd_vol()
			break
		if case("14"):
			print "Volume down pressed."
			__VolumeMan__.dec_vol()
			__LCDMan__.lcd_vol()
			break
		if case("18"):
			print "Select pressed."
			if __LCDMan__.lcd_base == __LCDMan__.base_menu:
				__LCDMenuMan__.menu_select()
			break
		if case("16"):
			print "Up pressed."
			if __LCDMan__.lcd_base == __LCDMan__.base_menu:
				__LCDMenuMan__.menu_up()
			break
		if case("17"):
			print "Down pressed."
			if __LCDMan__.lcd_base == __LCDMan__.base_menu:
				__LCDMenuMan__.menu_down()
			break
		if case("21"):
			print "Mute pressed."
			__VolumeMan__.toggle_mute()
			break
	__SerialPort__.flushInput()

def open_serial(portname, rate):
	global __SerialPort__
	if __SerialPort__ == None:
		print "Serial port does not exist, creating...",
		__SerialPort__ = serial.Serial(port=portname, baudrate=rate)
		print "done."
	else:
		print "Serial port alread exists!"
	if not __SerialPort__.isOpen:
		print "Serial port is not open, opeing...",
		__SerialPort__.open()
		print "done."

def main():
	global __MusicClient__
	global __MediaPlayer__
	global __LCDMan__
	global __LCDMenuMan__
	global __LastFm__
	global __VolumeMan__
	gpio.setmode(gpio.BCM)
	open_serial("/dev/ttyAMA0", 115200)
	__LCDMan__ = LCDManager()
	__LCDMan__.lcd_base = __LCDMan__.base_info
	__LCDMan__.info_lines = ["", "", "", ""]
	__LCDMan__.update()
	__LCDMan__.info_lines = ["Logging in to", "Google Play...", "", "Please wait..."]
	__LCDMan__.update()
	__SerialPort__.flushInput()
	__MusicClient__ = GPMClient("GOOGLE_EMAIL", "GOOGLE_PASSWORD", "DEVICE_ID")
	__LCDMan__.info_lines = ["Login Success.", "", "", ""]
	__LCDMan__.update()
	__SerialPort__.flushInput()
	__VolumeMan__ = VolumeManager(40)
	__MediaPlayer__ = MediaPlayer()
	__LCDMan__.info_lines = ["Updating local lib.", "from Google Play...", "", "Please Wait..."]
	__LCDMan__.update()
	__SerialPort__.flushInput()
	__MusicClient__.update_local_lib()
	__LCDMan__.info_lines = ["Logging in to", "Last.fm...", "", "Please wait..."]
	__LCDMan__.update()
	__SerialPort__.flushInput()
	__LastFm__ = LastfmScrobbler("LASTFM_USER", "LASTFM_PASS", False)
	__LCDMan__.info_lines = ["Google Play Music", "Ready!", "", ""]
	__LCDMan__.update()
	__SerialPort__.flushInput()
	
	__LCDMenuMan__ = LCDMenuManager()
	__LCDMan__.lcd_base = __LCDMan__.base_menu
	__LCDMenuMan__.menu_up()
	__LCDMan__.update()
	__SerialPort__.flushInput()
	
	while True:
		serial_handler()	
	thread.exit()

gobject.threads_init()
main()
