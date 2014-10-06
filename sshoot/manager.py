#
# This file is part of sshoot.

# sshoot is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.

# sshoot is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with sshoot.  If not, see <http://www.gnu.org/licenses/>.

"""Handle sshuttle sessions."""

import os
from signal import SIGTERM
from tempfile import gettempdir
from getpass import getuser
from subprocess import Popen, PIPE, CalledProcessError

from sshoot.profile import Profile, ProfileError
from sshoot.config import Config


DEFAULT_CONFIG_PATH = os.path.expanduser(os.path.join("~", ".sshoot"))


def get_rundir(prefix):
    """Return the directory holding runtime data."""
    return os.path.join(
        gettempdir(), "{prefix}-{username}".format(
            prefix=prefix, username=getuser()))


class ManagerProfileError(Exception):
    """Profile management failed."""


class Manager(object):

    kill = os.kill  # for testing

    def __init__(self, config_path=None, rundir=None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.rundir = rundir or get_rundir("sshoot")
        self.sessions_path = os.path.join(self.rundir, "sessions")
        self._config = Config(self.config_path)

    def load_config(self):
        """Load configuration from file."""
        if not os.path.exists(self.config_path):
            os.makedirs(self.config_path)
        if not os.path.exists(self.sessions_path):
            os.makedirs(self.sessions_path)

        self._config.load()

    def create_profile(self, name, details):
        """Create a profile with provided details."""
        try:
            profile = Profile.from_dict(details)
            self._config.add_profile(name, profile)
        except KeyError:
            raise ManagerProfileError(
                "Profile name already in use: {}".format(name))
        except ProfileError as e:
            raise ManagerProfileError(str(e))

        self._config.save()

    def remove_profile(self, name):
        """Remove profile with given name."""
        try:
            self._config.remove_profile(name)
        except KeyError:
            raise ManagerProfileError("Unknown profile: {}".format(name))

        self._config.save()

    def get_profiles(self):
        """Return profiles defined in config."""
        return self._config.profiles

    def get_profile(self, name):
        """Return profile with given name."""
        try:
            return self._config.profiles[name]
        except KeyError:
            raise ManagerProfileError("Unknown profile: {}".format(name))

    def start_profile(self, name):
        """Start profile with given name."""
        try:
            profile = self._config.profiles[name]
        except KeyError:
            raise ManagerProfileError("Unknown profile: {}".format(name))

        if self.is_running(name):
            raise ManagerProfileError("Profile is already running")

        executable = self._get_executable()
        extra_opts = ("--daemon", "--pidfile", self._get_pidfile(name))
        cmdline = profile.cmdline(executable=executable, extra_opts=extra_opts)

        message = "Profile failed to start: {}"
        try:
            process = Popen(cmdline, stdout=PIPE, stderr=PIPE)
            # Wait until process is started (it daemonizes)
            process.wait()
        except OSError as e:
            # To catch file not found errors
            raise ManagerProfileError(message.format(e))
        except CalledProcessError:
            pass  # The return code is checked anyway

        if process.returncode != 0:
            error = process.stderr.read()
            raise ManagerProfileError(message.format(error))

    def stop_profile(self, name):
        """Stop profile with given name."""
        try:
            self._config.profiles[name]
        except KeyError:
            raise ManagerProfileError("Unknown profile: {}".format(name))
        if not self.is_running(name):
            raise ManagerProfileError("Profile is not running")

        try:
            with open(self._get_pidfile(name)) as fh:
                self.kill(int(fh.read()), SIGTERM)
        except (IOError, OSError) as e:
            raise ManagerProfileError("Failed to stop profile: {}".format(e))

    def is_running(self, name):
        """Return whether the specified profile is running."""
        pidfile = self._get_pidfile(name)
        try:
            with open(pidfile) as fh:
                pid = int(fh.read())
        except Exception:
            # If anything fails, a valid pid can't be found, so the profile is
            # not running
            return False

        try:
            self.kill(pid, 0)
        except OSError:
            # Delete stale pidfile
            os.unlink(pidfile)
            return False
        return True

    def _get_pidfile(self, name):
        """Return the path of the pidfile for the specified profile."""
        return os.path.join(self.sessions_path, "{}.pid".format(name))

    def _get_executable(self):
        """Return the shuttle executable from the config."""
        return self._config.config.get("executable", "sshuttle")
