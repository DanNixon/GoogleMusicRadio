#!/usr/bin/python

## Google Play Music client script for Rasp. Pi radio
## Copyright: Dan Nixon 2012-13
## dan-nixon.com
## Version: 0.3.6
## Date: 25/06/2013

import thread, time, string
from gmusicapi import Webclient
from operator import itemgetter
import RPi.GPIO as gpio
import smbus
import pylast, serial
import gobject, glib, pygst
import gst

m_client = None
m_player = None
vol_man = None
lcd_man = None
lcd_menu_man = None
serial_port = None

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

class gMusicClient(object):
	logged_in = False
	api = None
	playlists = dict()
	library = dict()
	
	def __init__(self, email, password):
		print "Attempting login...",
		self.api = Webclient()
		logged_in = False
		attempts = 0
		while not self.logged_in and attempts < 3:
			self.logged_in = self.api.login(email, password)
			attempts += 1
		print "done."

	def __del__(self):
		print "Logging out...",
		self.api.logout()
		print "done."

	def updateLocalLib(self):
		songs = list()
		self.library = dict()
		self.playlists = dict()
		print "Updating local library...",
		songs = self.api.get_all_songs()
		print "done."
		print "Song count: ", len(songs)
		print "Building atrist and album dictionaries...",
		for song in songs:
			song_title = song["title"]
			if song["artist"] == "":
				song_artist = "Unknown Artist"
			else:
				song_artist = song["artist"]
			if song["album"] == "":
				song_album = "Unknown Album"
			else:
				song_album = song["album"]
			if not (song_artist in self.library):
				albums_dict = dict()
				self.library[song_artist] = albums_dict
			if not (song_album in self.library[song_artist]):
				song_list = list()
				self.library[song_artist][song_album] = song_list
			self.library[song_artist][song_album].append(song)
		print "done."
		print "Artist count: ", len(self.library)
		print "Updating playlists...",
		plists = self.api.get_all_playlist_ids(auto=True, user=True)
		for a_playlist, a_playlist_id in plists["auto"].iteritems():
			self.playlists[a_playlist] = self.api.get_playlist_songs(a_playlist_id[0])
		for u_playlist, u_playlist_id in plists["user"].iteritems():
			self.playlists[u_playlist] = self.api.get_playlist_songs(u_playlist_id[0])
		print "done."
		print "Playlist count: ", len(self.playlists)
		print "Library update complete."

	def getSongStream(self, song):
		url = self.api.get_stream_urls(song["id"])[0]
		return url
	
	def thumbsUp(self, song):
		try:
			song["rating"] = 5
			song_list = [song]
			self.api.change_song_metadata(song_list)
			print "Gave a Thumbs Up to {0} by {1} on Google Play.".format(song["title"], song["artist"])
		except:
			print "Error giving a Thumbs Up on Google Play."

class mediaPlayer(object):
	player = None
	now_playing_song = None
	queue = list()
	queue_index = -1
	
	def __init__(self):
		thread.start_new_thread(self.playerThread, ())
	
	def __del__(self):
		self.now_playing_song = None
		self.player.set_state(gst.STATE_NULL)
		
	def getPlayingSong(self):
		return self.now_playing_song
	
	def playerThread(self):
		if self.player == None:
			print "Creating a new GStreamer player..."
			self.player = gst.element_factory_make("playbin2", "player")
			self.player.set_state(gst.STATE_NULL)
			bus = self.player.get_bus()
			bus.add_signal_watch()
			bus.connect("message", self.songEndHandle)
			glib.MainLoop().run()
		else:
			print "Player already exists!"

	def playSong(self, song):
		global m_client
		global lcd_man
		global last_fm
		print "Song: ", song
		song_url = m_client.getSongStream(song)
		print "Got song URL: ", song_url
		try:
			print "Playing song."
			if not vol_man.is_mute:
				vol_man.setAmpPower(True)
			self.player.set_property("uri", song_url)
			self.player.set_state(gst.STATE_PLAYING)
			self.now_playing_song = song
			lcd_man.update()
		except AttributeError:
			print "Player does not yet exist!"
		last_fm.updateNowPlaying(song)

	def togglePlayback(self):
		global lcd_man
		try:
			player_state = self.player.get_state()[1]
			if player_state == gst.STATE_PAUSED:
				print "Resuming paused playback"
				if not vol_man.is_mute:
					vol_man.setAmpPower(True)
				self.player.set_state(gst.STATE_PLAYING)
				if lcd_man.lcd_base == lcd_man.BASE_PLAYING:
					lcd_man.update()
			elif player_state == gst.STATE_PLAYING:
				print "Pausing playback"
				self.player.set_state(gst.STATE_PAUSED)
				if not vol_man.is_mute:
					vol_man.setAmpPower(False)	
				if lcd_man.lcd_base == lcd_man.BASE_PLAYING:
					lcd_man.update()
			elif player_state == gst.STATE_NULL:
				print "Nothing in player"
				self.playNextInQueue()
				if lcd_man.lcd_base == lcd_man.BASE_PLAYING:
					lcd_man.update()
		except AttributeError:
			print "Player does not yet exist!"

	def stopPlayback(self):
		global lcd_man
		global vol_man
		try:
			print "Stopping playback"
			vol_man.setAmpPower(False)
			self.player.set_state(gst.STATE_NULL)
			self.now_playing_song = None
		except AttributeError:
			print "Player does not yet exist!"

	def songEndHandle(self, bus, message):
		if message.type == gst.MESSAGE_EOS:
			global last_fm
			last_fm.scrobbleSong(self.now_playing_song)
			self.stopPlayback()
			print "Finished playing last song"
			self.playNextInQueue()

	def playNextInQueue(self):
		global lcd_man
		print "Playing next song in queue"
		if not self.queue_index == (len(self.queue) - 1):
			self.queue_index = self.queue_index + 1
			next_song = self.queue[self.queue_index]
			self.playSong(next_song)
		else:
			self.stopPlayback()
			print "The queue is empty!"

	def addToQueue(self, song):
		print "Adding song to queue. Song ID: ", song["id"]
		self.queue.append(song)
		global lcd_menu_man
		lcd_menu_man.updateQueue()

	def nextSong(self):
		global last_fm
		last_fm.scrobbleSong(self.now_playing_song)
		self.stopPlayback()
		self.playNextInQueue()

class volumeManager(object):
	curr_vol = 0
	amp_on = False
	is_mute = False
	
	AMPPWR_GPIO = 24
	
	bus = None
	
	def __init__(self, init_vol):
		print "Setting up volume...",
		self.bus = smbus.SMBus(1)
		gpio.setup(self.AMPPWR_GPIO, gpio.OUT)
		gpio.output(self.AMPPWR_GPIO, gpio.HIGH)
		print "done."

	def __del__(self):
		gpio.output(self.AMPPWR_GPIO, gpio.HIGH)

	def toggleMute(self):
		self.is_mute = not self.is_mute
		amp_on = not self.is_mute
		self.setAmpPower(amp_on)
		if self.is_mute:
			print "Muted"
		else:
			print "Un muted"
		lcd_man.lcdAmpPower()

	def setAmpPower(self, on):
		global lcd_man
		if on:
			gpio.output(self.AMPPWR_GPIO, gpio.LOW)
		else:
			gpio.output(self.AMPPWR_GPIO, gpio.HIGH)
		self.amp_on = on
		bVol = 64 - self.curr_vol
		time.sleep(0.25)
		self.bus.write_byte_data(0x28, 0xAF, bVol)
	
	def incVol(self):
		print "Volume++",
		if not ((self.curr_vol + 1) == 64):
			self.curr_vol += 1
			dpVol = 64 - self.curr_vol
			self.bus.write_byte_data(0x28, 0xAF, dpVol)
			print "New volume: {0}".format(self.curr_vol)
		else:
			print "Max volume!"

	def decVol(self):
		print "Volume--",
		if not ((self.curr_vol - 1) == -1):
			self.curr_vol -= 1
			dpVol = 64 - self.curr_vol
			self.bus.write_byte_data(0x28, 0xAF, dpVol)
			print "New volume: {0}".format(self.curr_vol)
		else:
			print "Min volume!"

class lcdMenuManager(object):
	menu_struct = dict()
	menu_level = 0
	menu_history = list()
	menu_index = 0
	cursor_pos = 0
	list_pos = 0
	current_menu_display = list()
	LCD_COLS = 0
	
	def __init__(self):
		global lcd_man
		self.LCD_COLS = lcd_man.LCD_COLS
		self.initStruct()
	
	def updateQueue(self):
		global m_player
		if not (len(m_player.queue) == 0):
			self.menu_struct["Queue"] = m_player.queue
		else:
			self.menu_struct["Queue"] = ["Queue Empty"]
	
	def initStruct(self):
		global m_client
		self.updateQueue()
		self.menu_struct["Playlists"] = m_client.playlists
		self.menu_struct["Settings"] = {'Reload Library':'LIB_RELOAD', 'Toggle Scrobbling':'LASTFM_TOGGLE'}
		#MOD_VERIF
		self.menu_struct["Library"] = {	'A':dict(),'B':dict(),'C':dict(),
										'D':dict(),'E':dict(),'F':dict(),
										'G':dict(),'H':dict(),'I':dict(),
										'J':dict(),'K':dict(),'L':dict(),
										'M':dict(),'N':dict(),'O':dict(),
										'P':dict(),'Q':dict(),'R':dict(),
										'S':dict(),'T':dict(),'U':dict(),
										'V':dict(),'W':dict(),'X':dict(),
										'Y':dict(),'Z':dict(),'#':dict()}
		for artist, data in m_client.library.iteritems():
			name_letter = artist[:1].upper()
			if name_letter in string.ascii_uppercase:
				self.menu_struct["Library"][name_letter][artist] = data
			else:
				self.menu_struct["Library"]['#'][artist] = data
	
	def renderMenu(self):
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
			if self.menu_history[0] == "Playlists":
				print "Showing playlists, will sort for LCD"
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
				break;
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
		line1 = lcd_man.asciiFilter(line1)
		line2 = lcd_man.asciiFilter(line2)
		line3 = lcd_man.asciiFilter(line3)
		line4 = lcd_man.asciiFilter(line4)
		for case in switch(self.cursor_pos):
			if case(0):
				line1 = ("{}{}".format(">", line1))[:self.LCD_COLS]
				line2 = ("{}{}".format(" ", line2))[:self.LCD_COLS]
				line3 = ("{}{}".format(" ", line3))[:self.LCD_COLS]
				line4 = ("{}{}".format(" ", line4))[:self.LCD_COLS]
				break
			if case(1):
				line1 = ("{}{}".format(" ", line1))[:self.LCD_COLS]
				line2 = ("{}{}".format(">", line2))[:self.LCD_COLS]
				line3 = ("{}{}".format(" ", line3))[:self.LCD_COLS]
				line4 = ("{}{}".format(" ", line4))[:self.LCD_COLS]
				break
			if case(2):
				line1 = ("{}{}".format(" ", line1))[:self.LCD_COLS]
				line2 = ("{}{}".format(" ", line2))[:self.LCD_COLS]
				line3 = ("{}{}".format(">", line3))[:self.LCD_COLS]
				line4 = ("{}{}".format(" ", line4))[:self.LCD_COLS]
				break
			if case(3):
				line1 = ("{}{}".format(" ", line1))[:self.LCD_COLS]
				line2 = ("{}{}".format(" ", line2))[:self.LCD_COLS]
				line3 = ("{}{}".format(" ", line3))[:self.LCD_COLS]
				line4 = ("{}{}".format(">", line4))[:self.LCD_COLS]
				break
		global lcd_man
		lcd_man.menu_lines = [line1, line2, line3, line4]
		print "MENU:", lcd_man.menu_lines
		lcd_man.update()
	
	def menuUp(self):
		if not (self.menu_index == 0):
			self.menu_index = self.menu_index - 1
			if self.cursor_pos == 2:
				self.cursor_pos = 1
		self.renderMenu()
	
	def menuDown(self):
		if not (self.menu_index == (len(self.current_menu_display) - 1)):
			self.menu_index = self.menu_index + 1
			if not (self.cursor_pos == 2):
				self.cursor_pos = self.cursor_pos + 1
		self.renderMenu()
	
	def menuSelect(self):
		global m_player
		global m_client
		global lcd_man
		global last_fm
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
							for case in switch(m_player.queue_index):
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
									self.menu_index = m_player.queue_index
									break
						self.menu_history.append("Queue")
						break;
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
								m_player.stopPlayback()
								lcd_man.lcd_base = lcd_man.BASE_INFO
								lcd_man.info_lines = ["Updating local lib.", "from Google Play...", "", "Please Wait..."]
								lcd_man.update()
								m_client.updateLocalLib()
								self.initStruct()
								lcd_man.lcd_base = lcd_man.BASE_MENU
								lcd_man.update()
								break
							if case("Toggle Scrobbling"):
								print "Last.fm menu option selected"
								last_fm.toggleScrobbling()
								lcd_man.lcdLastfmToggle()
								no_lcd_update = True
								break
						break
					if case("Queue"):
						if not (selected_item == "Queue Empty"):
								print "On queue, a song was selected."
								m_player.queue_index = (self.menu_index - 1)
								m_player.nextSong()
								lcd_man.lcd_base = lcd_man.BASE_PLAYING
								lcd_man.update()
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
						queue_len = len(m_player.queue)
						m_player.queue_index = queue_len + self.menu_index - 1
						for song in plist_songs:
							m_player.addToQueue(song)
						m_player.nextSong()
						lcd_man.lcd_base = lcd_man.BASE_PLAYING
						lcd_man.update()
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
				queue_len = len(m_player.queue)
				m_player.queue_index = queue_len + self.menu_index - 1
				for song in album_songs:
					m_player.addToQueue(song)
				m_player.nextSong()
				lcd_man.lcd_base = lcd_man.BASE_PLAYING
				lcd_man.update()
				break
		if not no_lcd_update:
			self.renderMenu()
	
	def menuReturn(self):
		if not (self.menu_level == 0):
			self.menu_level = self.menu_level - 1
			self.curr_pos = 0
			self.menu_index = 0
			self.menu_history.pop()
			self.renderMenu()

class lcdManager(object):
	BASE_INFO = 0
	BASE_PLAYING = 1
	BASE_VOLUME = 2
	BASE_MENU = 3
	BASE_LOVED = 4
	BASE_AMP = 5
	
	BL_GPIO = 23
	LCD_TIMEOUT = 60
	
	LCD_COLS = 20
	
	backlight_timeout = 0
	backlight_on = False
	lcd_base = BASE_INFO
	timeout = 0
	timer_run = False
	menu_lines = list()
	info_lines = list()
	
	def __init__(self):
		gpio.setup(self.BL_GPIO, gpio.OUT)
		gpio.output(self.BL_GPIO, gpio.LOW)
		self.backlight_on = True
		self.backlight_timestart = time.time()
		thread.start_new_thread(self.backlightManager, ())

	def __del__(self):
		gpio.output(self.BL_GPIO, gpio.HIGH)

	def asciiFilter(self, string):
		result = ''
		for char in string:
			if ord(char) < 128:
				result += char
			else:
				result += '?'
		return result
	
	def backlightManager(self):
		while True:
			end_time = self.backlight_timestart + self.LCD_TIMEOUT
			if time.time() > end_time:
				self.setBacklight(False)
			else:
				self.setBacklight(True)
	
	def setBacklight(self, bl_on):
		if not (bl_on == self.backlight_on):
			if bl_on:
				gpio.output(self.BL_GPIO, gpio.LOW)
				print "LCD backlight on"
			else:
				gpio.output(self.BL_GPIO, gpio.HIGH)
				print "LCD backlight off"
			self.backlight_on = bl_on
	
	def writeLCD(self, line1, line2, line3, line4):
		global serial_port
		if not serial_port == None:
			if serial_port.isOpen():
				serial_port.write("24~") ##Arduino Change
				time.sleep(0.02)
				serial_port.write("22%0%" + self.asciiFilter(line1)[:self.LCD_COLS] + "~") ##Arduino Change
				time.sleep(0.02)
				serial_port.write("22%1%" + self.asciiFilter(line2)[:self.LCD_COLS] + "~") ##Arduino Change
				time.sleep(0.02)
				serial_port.write("22%2%" + self.asciiFilter(line3)[:self.LCD_COLS] + "~") ##Arduino Change
				time.sleep(0.02)
				serial_port.write("22%3%" + self.asciiFilter(line4)[:self.LCD_COLS] + "~") ##Arduino Change
			else:
				print "Serial port is not open!"
		else:
			print "Serial port does not exist!"
	
	def update(self):
		global m_player
		global last_fm
		for case in switch(self.lcd_base):
			if case(self.BASE_INFO):
				self.writeLCD(self.info_lines[0], self.info_lines[1], self.info_lines[2], self.info_lines[3])
				break
			if case(self.BASE_PLAYING):
				song = m_player.getPlayingSong()
				info_line_list = list()
				player_state = m_player.player.get_state()[1]
				if player_state == gst.STATE_PLAYING:
					info_line_list.append("Playing  ")
				if player_state == gst.STATE_PAUSED:
					info_line_list.append("Paused   ")
				if last_fm.scrobbles_enabled:
					info_line_list.append("Last.fm On  ")
				else:
					info_line_list.append("Last.fm Off ")
				if not song == None:
					self.writeLCD(song["title"], song["artist"], song["album"], ''.join(info_line_list))
				else:
					self.writeLCD("No song playing.", "", "", info_line)
				break
			if case(self.BASE_VOLUME):
				global vol_man
				global serial_port
				serial_port.write("23%" + format(vol_man.curr_vol) + "~") ##Arduino Change
				break
			if case(self.BASE_MENU):
				self.writeLCD(self.menu_lines[0], self.menu_lines[1], self.menu_lines[2], self.menu_lines[3])
				break
			if case(self.BASE_LOVED):
				song = m_player.getPlayingSong()
				self.writeLCD(song["title"], song["artist"], "Loved on Last.fm", "Thumbs up on Play")
				break
			if case(self.BASE_AMP):
				if vol_man.amp_on:
					en_string = "Enabled"
				else:
					en_string = "Disabled"
				self.writeLCD("", "Internal Amplifier:", en_string, "")
				break

	def timerThread(self):
		while self.timer_run:
			if time.time() > self.timeout:
				self.update()
				self.timer_run = False
				print "Timer end."
				return

	def initTimer(self, deltat):
		self.timeout = time.time() + deltat
		if not self.timer_run:
			self.timer_run = True
			thread.start_new_thread(self.timerThread, ())
	
	def lcdAmpPower(self):
		base_last = self.lcd_base
		self.lcd_base = self.BASE_AMP
		self.update()
		self.lcd_base = base_last
		self.initTimer(3)
	
	def lcdLoved(self):
		base_last = self.lcd_base
		self.lcd_base = self.BASE_LOVED
		self.update()
		self.lcd_base = base_last
		self.initTimer(3)

	def lcdVol(self):
		base_last = self.lcd_base
		if not self.timer_run:
			self.update()
		self.lcd_base = self.BASE_VOLUME
		self.update()
		self.lcd_base = base_last
		self.initTimer(3)
	
	def lcdLastfmToggle(self):
		self.lcd_base = lcd_man.BASE_INFO
		string = ""
		global last_fm
		if last_fm.scrobbles_enabled:
			string = "Enabled"
		else:
			string = "Disabled"
		self.info_lines = ["Last.fm Scrobbling:", string, "", ""]
		self.update()
		self.lcd_base = lcd_man.BASE_MENU
		self.initTimer(3)

class lastfmScrobbler(object):
	API_KEY = "3b918147d7533ddb46cbf8c90c7c4b63"
	API_SECRET = "feb61d4de652b7223ab2341a4e436668"
	session = None
	scrobbles_enabled = True
	
	def __init__(self, username, password):
		print "Last.fm login...",
		password_hash = pylast.md5(password)
		self.session = pylast.LastFMNetwork(api_key = self.API_KEY, api_secret = self.API_SECRET, username = username, password_hash = password_hash)
		print "done."
	
	def loveSong(self, song):
		if not song == None:
			thread.start_new_thread(self.workerFunction, (1, song))
	
	def updateNowPlaying(self, song):
		if not song == None:
			thread.start_new_thread(self.workerFunction, (2, song))
		
	def scrobbleSong(self, song):
		if self.scrobbles_enabled and not (song == None):
			thread.start_new_thread(self.workerFunction, (3, song))
	
	def toggleScrobbling(self):
		self.scrobbles_enabled = not self.scrobbles_enabled
		print "Scrobbling enabled:", self.scrobbles_enabled
	
	def workerFunction(self, function, song):
		title = song['title']
		artist = song['artist']
		if artist == "":
			artist = "Unknown Artist"
		for case in switch(function):
			if case(1):
				print "Loving song: ", artist, ",", title
				track = self.session.get_track(artist, title)
				print track.love()
				break
			if case(2):
				print "Updating Last.fm now playing, song:", artist, ",", title
				print self.session.update_now_playing(artist, title)
				break
			if case(3):
				print "Scrobbling play to Last.fm, song:", artist, ",", title
				print self.session.scrobble(artist, title, int(time.time()))
				break
	
def serialHandler():
	global serial_port
	global m_player
	global vol_man
	global lcd_man
	global lcd_menu_man
	global last_fm
	time.sleep(0.01)
	data = serial_port.read(2)
	lcd_man.backlight_timestart = time.time()
	player_state = m_player.player.get_state()[1]  #MOD_VERIF
	for case in switch(data): ##Arduino Change
		if case("11"):
			print "Stop button pressed."
			m_player.stopPlayback()
			lcd_man.lcd_base = lcd_man.BASE_MENU
			lcd_man.update()
			break
		if case("12"):
			print "Play button pressed."
			m_player.togglePlayback()
			break
		if case("10"):
			print "Next button pressed."
			m_player.nextSong()
			break
		if case("20"):
			print "Love pressed."
			if player_state == gst.STATE_PLAYING or player_state == gst.STATE_PAUSED: #MOD_VERIF
				lcd_man.lcdLoved()
				last_fm.loveSong(m_player.now_playing_song)
				m_client.thumbsUp(m_player.now_playing_song)
			break
		if case("19"):
			print "Display pressed."
			for case in switch(lcd_man.lcd_base):
				if case(lcd_man.BASE_MENU):
					if player_state == gst.STATE_PLAYING or player_state == gst.STATE_PAUSED: #MOD_VERIF
						lcd_man.lcd_base = lcd_man.BASE_PLAYING
						lcd_man.update()
					break
				if case(lcd_man.BASE_PLAYING):
					lcd_man.lcd_base = lcd_man.BASE_MENU
					lcd_man.update()
					break
			break
		if case("13"):
			print "Back pressed."
			if lcd_man.lcd_base == lcd_man.BASE_MENU:
				lcd_menu_man.menuReturn()
			break
		if case("15"):
			print "Volume up pressed."
			vol_man.incVol()
			lcd_man.lcdVol()
			break
		if case("14"):
			print "Volume down pressed."
			vol_man.decVol()
			lcd_man.lcdVol()
			break
		if case("18"):
			print "Select pressed."
			if lcd_man.lcd_base == lcd_man.BASE_MENU:
				lcd_menu_man.menuSelect()
			break
		if case("16"):
			print "Up pressed."
			if lcd_man.lcd_base == lcd_man.BASE_MENU:
				lcd_menu_man.menuUp()
			break
		if case("17"):
			print "Down pressed."
			if lcd_man.lcd_base == lcd_man.BASE_MENU:
				lcd_menu_man.menuDown()
			break
		if case("21"):
			print "Mute pressed."
			vol_man.toggleMute();
			break
	serial_port.flushInput()

def openSerial(portname, rate):
	global serial_port
	if serial_port == None:
		print "Serial port does not exist, creating...",
		serial_port = serial.Serial(port=portname, baudrate=rate)
		print "done."
	else:
		print "Serial port alread exists!"
	if not serial_port.isOpen:
		print "Serial port is not open, opeing...",
		serial_port.open()
		print "done."

def main():
	gpio.setmode(gpio.BCM)
	global m_client
	global m_player
	global vol_man
	global lcd_man
	global lcd_menu_man
	global last_fm
	openSerial("/dev/ttyAMA0", 115200)
	global serial_port
	lcd_man = lcdManager()
	lcd_man.lcd_base = lcd_man.BASE_INFO
	lcd_man.info_lines = ["Logging in...", "", "", ""]
	lcd_man.update()
	serial_port.flushInput()
	m_client = gMusicClient("GOOGLE_USER", "GOOGLE_PASS")
	lcd_man.info_lines = ["Login Success.", "", "", ""]
	lcd_man.update()
	serial_port.flushInput()
	vol_man = volumeManager(40)
	m_player = mediaPlayer()
	lcd_man.info_lines = ["Updating local lib.", "from Google Play...", "", ""]
	lcd_man.update()
	serial_port.flushInput()
	m_client.updateLocalLib()
	lcd_man.info_lines = ["Logging in to", "Last.fm...", "", ""]
	lcd_man.update()
	serial_port.flushInput()
	last_fm = lastfmScrobbler("LASTFM_USER", "LASTFM_PASS")
	lcd_man.info_lines = ["Google Play Music", "Ready!", "", ""]
	lcd_man.update()
	serial_port.flushInput()
	
	lcd_menu_man = lcdMenuManager()
	lcd_man.lcd_base = lcd_man.BASE_MENU
	lcd_menu_man.menuUp()
	lcd_man.update()
	serial_port.flushInput()
	
	while True:
		serialHandler()	
	thread.exit()

gobject.threads_init()
main()
