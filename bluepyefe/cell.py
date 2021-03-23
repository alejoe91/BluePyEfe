"""Cell class"""

"""
Copyright (c) 2020, EPFL/Blue Brain Project

 This file is part of BluePyEfe <https://github.com/BlueBrain/BluePyEfe>

 This library is free software; you can redistribute it and/or modify it under
 the terms of the GNU Lesser General Public License version 3.0 as published
 by the Free Software Foundation.

 This library is distributed in the hope that it will be useful, but WITHOUT
 ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
 FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
 details.

 You should have received a copy of the GNU Lesser General Public License
 along with this library; if not, write to the Free Software Foundation, Inc.,
 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""


import efel

from bluepyefe.ecode import eCodes
from bluepyefe.reader import *

logger = logging.getLogger(__name__)


class Cell(object):

    """Contains the metadata related to the cell as well as the recordings data
    once these are read"""

    def __init__(self, name, recording_reader=None):
        """
        Constructor

        Args:
            name (str): name of the cell.
            recording_reader (function): custom recording reader matching the
                files metadata.
        """

        self.name = name

        self.recordings = []
        self.rheobase = None

    def reader(self, config_data, recording_reader=None):

        if "v_file" in config_data:
            filename = config_data["v_file"]
        elif "filepath" in config_data:
            filename = config_data["filepath"]

        if recording_reader:
            return recording_reader(config_data)
        if ".abf" in filename:
            return axon_reader(config_data)
        if ".ibw" in filename:
            return igor_reader(config_data)
        if ".nwb" in filename:
            return nwb_reader_BBP(config_data)

        raise Exception(
            "The format of the files is unknown and no custom reader were"
            " provided."
        )

    def get_protocol_names(self):
        return list(set([rec.protocol_name for rec in self.recordings]))

    def get_recordings_by_protocol_name(self, protocol_name):
        return [
            rec
            for rec in self.recordings
            if rec.protocol_name == protocol_name
        ]

    def get_recordings_id_by_protocol_name(self, protocol_name):
        return [
            i
            for i, trace in enumerate(self.recordings)
            if trace.protocol_name == protocol_name
        ]

    def read_recordings(
        self, protocol_data, protocol_name, recording_reader=None
    ):
        """
        For each recording's metadata, instance a recording object and
        populate it by reading the matching data file.
        """

        for config_data in protocol_data:
            for reader_data in self.reader(config_data, recording_reader):

                if protocol_name.lower() in eCodes.keys():
                    rec = eCodes[protocol_name.lower()](
                        config_data, reader_data, protocol_name
                    )

                    self.recordings.append(rec)
                else:
                    raise KeyError(
                        "There is no eCode linked to the stimulus name {}. "
                        "See ecode/__init__.py for the available stimuli "
                        "names".format(protocol_name.lower())
                    )

    def efeatures_from_recording(self, recording, efeatures):
        """
        Calls efel to computed the wanted efeatures.In a first time,
        computes features that have are to be computed between ton
        and toff, then compute the features that use custom stim_start
        and stim_end.
        """

        efel.setDoubleSetting("stimulus_current", recording.amp)

        efel_trace = [
            {
                "T": recording.t,
                "V": recording.voltage,
                "stim_start": [recording.ton],
                "stim_end": [recording.toff],
            }
        ]

        efel_efeatures = [
            f
            for f in efeatures
            if efeatures[f] is None or not (len(efeatures[f]))
        ] + ["peak_time"]

        fel_vals = efel.getFeatureValues(
            efel_trace, efel_efeatures, raise_warnings=False
        )

        recording.spikecount = len(fel_vals[0]["peak_time"])
        efel_efeatures.remove("peak_time")

        for efeature in efel_efeatures:

            f = fel_vals[0][efeature]

            if f is None:
                f = numpy.nan

            recording.efeatures[efeature] = numpy.nanmean(f)

        for f in efeatures:

            if efeatures[f] is not None and len(efeatures[f]):

                efel_trace[-1]["stim_start"] = [efeatures[f][0]]
                efel_trace[-1]["stim_end"] = [efeatures[f][1]]

                fel_vals = efel.getFeatureValues(
                    efel_trace, [f], raise_warnings=False
                )

                if fel_vals[0][f] is not None:
                    recording.efeatures[f] = numpy.nanmean(fel_vals[0][f])
                else:
                    recording.efeatures[f] = numpy.nan

        return recording

    def extract_efeatures(
        self, protocol_name, efeatures, ap_threshold=-20.0, strict_stim=True
    ):
        """
        Extract the efeatures for the recordings matching the protocol name.
        """

        efel.setThreshold(ap_threshold)
        efel.setIntSetting("strict_stiminterval", strict_stim)

        for i in self.get_recordings_id_by_protocol_name(protocol_name):
            self.recordings[i] = self.efeatures_from_recording(
                self.recordings[i], efeatures=efeatures
            )

    def compute_rheobase(self, protocols_rheobase):
        """
        Compute the rheobase by finding the smallest current amplitude
        triggering at least one spike.
        """

        amps = []

        for i, rec in enumerate(self.recordings):
            if rec.protocol_name in protocols_rheobase:
                if rec.spikecount is not None and rec.spikecount > 0:

                    if rec.amp < 0.01:
                        logger.warning(
                            "A recording of cell {} protocol {} shows spikes"
                            " at a suspiciously low current. Check ton and"
                            " toff.".format(self.name, rec.protocol_name)
                        )

                    amps.append(rec.amp)

        if len(amps):
            self.rheobase = numpy.min(amps)

    def compute_relative_amp(self):
        """
        Compute the relative current amplitude for all the recordings as a
        percentage of the rheobase.
        """

        if self.rheobase not in (0.0, None, False, numpy.nan):

            for i in range(len(self.recordings)):
                self.recordings[i].compute_relative_amp(self.rheobase)

        else:

            logger.warning(
                "Cannot compute the relative current amplitude for the "
                "recordings of cell {} because its rheobase is {}."
                "".format(
                    self.name, self.rheobase
                )
            )
            self.rheobase = None