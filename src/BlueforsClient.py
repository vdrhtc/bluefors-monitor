import csv
import os
import re
import socket
import urllib
from datetime import datetime
from threading import Thread
from time import sleep
import ssl

from numpy import reshape, log10

from src.LoggingServer import LoggingServer


class BlueforsClient:

    def __init__(self, nickname, password, server_address, server_port, logs_path):

        self._server_address = server_address
        self._password = password
        self._server_port = server_port
        self._logs_path = logs_path
        self._nickname = nickname
        self._logger = LoggingServer.getInstance()

        self._context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        self._context.verify_mode = ssl.CERT_REQUIRED
        certurl = "https://raw.githubusercontent.com/vdrhtc/overseer/master/domain.crt"
        self._certfile = urllib.request.urlretrieve(certurl)[0]
        self._context.load_verify_locations(self._certfile)

        self._secure_socket = self._context.wrap_socket(socket.socket())  # instantiate

        self._secure_socket.connect((server_address, server_port))  # connect to the server

        self._stop = False
        self._updater = Thread(target=self._act)
        self._updater.setDaemon(True)

        self._strategies = {"update": self._send_update,
                            "reconnect": self._reconnect,
                            "handshake": self._handshake}
        self._current_strategy = "handshake"

    def launch(self):
        self._stop = False
        self._updater.start()

    def _act(self):
        while not self._stop:
            try:
                self._strategies[self._current_strategy]()
            except (TimeoutError, ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError, ConnectionError) as e:
                self._logger.warn(str(e))
                sleep(15)
                self._current_strategy = "reconnect"
            except Exception as e:
                self._logger.warn(str(e))
                print(e)
                break
        self._secure_socket.close()

    def _send_update(self):
        print("\rSending update, " + str(datetime.now()), end="")
        try:
            data = self.generate_info_message().encode()
        except Exception as e:
            data = str(e).encode()

        self._secure_socket.send(data)
        sleep(15)

    def _reconnect(self):
        print("\rReconnecting...", end="")

        self._secure_socket.close()
        self._secure_socket = self._context.wrap_socket(socket.socket())
        self._secure_socket.connect((self._server_address, self._server_port))  # connect to the server
        self._current_strategy = "handshake"

    def _handshake(self):
        self._secure_socket.send((self._nickname+"\r\n"+self._password).encode())
        response = self._secure_socket.recv(1024).decode()
        if response == self._nickname:
            self._current_strategy = "update"
            print("Successful handshake!")
        else:
            print(" "+response, end="")
            self._current_strategy = "reconnect"
            sleep(15)

    def generate_info_message(self):
        on_off = {"0": "⚪️", "1": "🔵", "2": '🌕'}

        ######### Status
        last_state_dict = dict(reshape(self.get_state(0)[3:], (-1, 2)))
        status_dict = dict(reshape(self.get_status()[2:], (-1, 2)))
        if (last_state_dict["pulsetube"] == "1") + (
                (float(status_dict['cptempwo']) - float(status_dict['cptempwi'])) > 13) == 1:
            # observables contradict
            last_state_dict["pulsetube"] = "2"

        if (last_state_dict["turbo1"] == "1") + (float(status_dict["tc400setspdatt"]) == 1) == 1:
            # observables contradict
            last_state_dict["turbo1"] = "2"

        main_keys = ["scroll1", "scroll2", "turbo1", "compressor", "pulsetube"]
        main_names = ["scr1 scr2 tur1 comp pt"]
        state_string = "`" + "".join("{0:<4s}".format(key) for key in (main_names)) + "\n"
        state_string += "".join("{0:s}   ".format(on_off[last_state_dict[key]]) for key in (main_keys)) + "`"

        ########## Changes
        changes = self.get_last_state_change()
        time_since_last_change = datetime.now() - changes["change_time"]
        del changes["change_time"]

        changes_string = "`" + " ".join(
            "{0:s}{1:s}".format(key, on_off[changes[key]]) for key in sorted(changes.keys())) + "`"

        ########## Temps
        temperature_names, temperatures = self.get_last_temperatures()
        temp_string = "`" + "\n".join(["{0:>6s}: {1:.2f} K".format(channel, float(last_temp)) if
                                       float(last_temp) > 1 else "{0:>6s}: {1:.2f} mK".format(channel,
                                                                                              1000 * float(last_temp))
                                       for channel, last_temp in zip(temperature_names, temperatures)]) + "`"
        ########## Pressures
        pressure_names, pressures = self.get_last_pressures()
        pressures_string = "`" + "\n".join("{0:>6s}: {1:15s}".format(name, self.format_unicode_sci(pressure) + " mBar")
                                           for name, pressure in zip(pressure_names, pressures)) + "`"

        message = "%s\n%s @ BF LD250" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), self._nickname)
        message += "\n\nCurrent state:\n" + state_string
        message += "\n\nLast change (" + self.format_timedelta(time_since_last_change) + " ago):\n" + changes_string
        message += "\n\nTemperatures:\n" + temp_string
        message += "\n\nPressures:\n"
        message += pressures_string
        return message

    def get_status(self):
        logs_path = self._logs_path
        dates = os.listdir(logs_path)[:]
        dates = list(filter(re.compile(r'(\d+-\d+-\d+)').match, dates))
        date_idx = -1
        date = dates[date_idx]

        try:
            status_file = [file for file in os.listdir(logs_path + date) if bool(re.search("Status", file))][0]
        except IndexError:
            date_idx -= 1
            date = dates[date_idx]
            status_file = [file for file in os.listdir(logs_path + date) if bool(re.search("Status", file))][0]

        with open(logs_path + date + "/" + status_file, "r") as f:
            statuses = f.readlines()

        statuses = list(csv.reader(statuses))

        return statuses[-1]

    def get_state(self, depth):
        logs_path = self._logs_path
        dates = os.listdir(logs_path)[:]
        dates = list(filter(re.compile(r'(\d+-\d+-\d+)').match, dates))
        date_idx = -1

        states = []
        while len(states) < depth + 1:  # gathering states from
            date = dates[date_idx]
            try:
                state_file = [file for file in os.listdir(logs_path + date) if bool(re.search("Channels", file))][0]
                with open(logs_path + date + "/" + state_file, "r") as f:
                    states = f.readlines() + states
                date_idx -= 1
            except IndexError:
                date_idx -= 1  # probably yet no changes this day

        states = list(csv.reader(states))

        return states[-(depth + 1)]

    def get_last_state_change(self):

        change = {}
        depth = 0
        while len(change) <= 1:
            last_state_list = self.get_state(depth)
            last_state = dict(reshape(last_state_list[3:], (-1, 2)))
            previous_state = dict(reshape(self.get_state(depth + 1)[3:], (-1, 2)))
            change = dict(set(last_state.items()) - set(previous_state.items()))
            change["change_time"] = datetime.strptime(last_state_list[0] + " " + last_state_list[1],
                                                      "%d-%m-%y %H:%M:%S")
            depth += 1
        return change

    def get_last_pressures(self):
        logs_path = self._logs_path
        dates = os.listdir(logs_path)[:]
        dates = list(filter(re.compile(r'(\d+-\d+-\d+)').match, dates))
        date = dates[-1]
        try:
            maxigauge_file = [file for file in os.listdir(logs_path + date) if bool(re.search("maxigauge", file))][0]
        except IndexError:
            date = dates[-2]
            maxigauge_file = [file for file in os.listdir(logs_path + date) if bool(re.search("maxigauge", file))][0]

        with open(logs_path + date + "/" + maxigauge_file, "r") as f:
            maxigauge = f.readlines()

        for row in csv.reader(maxigauge):
            t = datetime.strptime(row[0] + " " + row[1], "%d-%m-%y %H:%M:%S")
            p_vals = [float(row[5 + i * 6]) for i in range(0, 6)]
            p_names = [(row[3 + i * 6]).strip() for i in range(0, 6)]

        p_names[0] = "Сan"
        p_names[1] = "Turbo"
        p_names[4] = "Tank"
        p_names[5] = "Vent"
        return p_names, p_vals

    def get_last_temperatures(self):
        temperature_logs_path = self._logs_path
        dates = os.listdir(temperature_logs_path)[:]
        dates = list(filter(re.compile(r'(\d+-\d+-\d+)').match, dates))

        date = dates[-1]
        channel_files = [file for file in os.listdir(temperature_logs_path + date) if bool(re.search("CH. T", file))]

        last_temps = []
        for channel_file in channel_files:
            with open(temperature_logs_path + date + "/" + channel_file, "r") as f:
                temps = f.readlines()
            last_temps.append(float(temps[-1].split(",")[-1][:-1]))
        channel_names = [channel_file[:3] for channel_file in channel_files]

        return channel_names, last_temps

    @staticmethod
    def format_unicode_sci(number):
        try:
            exponent = int(round(log10(abs(number))))
            if exponent < 0:
                mantis = number / 10 ** exponent

                SUP = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")

                return "%.2f·10" % mantis + str(exponent).translate(SUP)
            else:
                raise ValueError("Conversion not needed")
        except Exception:
            return str(number)

    @staticmethod
    def format_timedelta(td):
        s = td.total_seconds()

        days = s//(3600*24)
        if days >= 2:
            return "%sd"%int(days)

        hours, remainder = divmod(s, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return '{:}h {:}m {:}s'.format(int(hours), int(minutes), int(seconds))
        elif minutes > 0:
            return '{:}m {:}s'.format(int(minutes), int(seconds))
        else:
            return '{:}s'.format(int(seconds))
