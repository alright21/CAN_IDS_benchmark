import threading
import time
import can
import logging
from base64 import b64encode, b64decode
import datetime
import sys


# Reference: https://www.bogotobogo.com/python/Multithread/python_multithreading_Synchronization_Producer_Consumer_using_Queue.php
logging.basicConfig(level=logging.INFO, format='(%(threadName)-9s) %(message)s',)


class CSVReader(can.io.generic.BaseIOHandler):
    """Iterator over CAN messages from a .csv file that was
    generated by :class:`~can.CSVWriter` or that uses the same
    format as described there. Assumes that there is a header
    and thus skips the first line.

    Any line separator is accepted.
    """

    def __init__(self, file):
        """
        :param file: a path-like object or as file-like object to read from
                     If this is a file-like object, is has to opened in text
                     read mode, not binary read mode.
        """
        super(CSVReader, self).__init__(file, mode='r')

    def __iter__(self):
        # skip the header line
        try:
            next(self.file)
        except StopIteration:
            # don't crash on a file with only a header
            return

        for row,line in enumerate(self.file):

            timestamp, arbitration_id, extended, remote, error, dlc, data0, data1, data2, data3, data4, data5, data6, data7 = line.split(',')

            date, time = timestamp.split(' ')
            year, month, day = date.split('-')
            hour, minute, seconds = time.split(':')
            second, microsecond = seconds.split('.')

            dt = datetime.datetime(int(year), int(month), int(day), int(hour), int(minute), int(second), int(microsecond))
            data_temp = [data0 , data1, data2, data3, data4, data5, data6, data7.rstrip('\n')]

            data = []
            for i in range(len(data_temp)):
                if data_temp[i] != '':
                    data.append(int(data_temp[i]))
            yield can.Message(
                timestamp=dt.timestamp(),
                is_remote_frame=(True if dlc=='0' else False),
                is_extended_id=(True),
                is_error_frame=(False),
                arbitration_id=int(arbitration_id, base=16),
                dlc=int(dlc),
                data=(data if dlc!='0' else None),
                check=True
            )

        self.stop()

# producer class, simulated with CSV log data
class ProducerThread(threading.Thread):
    def __init__(self, bus=None, group=None, target=None, name=None, args=(), kwargs=None, verbose=None):
        super(ProducerThread, self).__init__()
        self.target = target
        self.name = name
        self.bus = bus
        return

    def run(self):
        i = 0
        last_timestamp = 0.0
        for msg in CSVReader('/home/alright/TURKU/thesis/data/CAN-Vehicle/2020_12_04_15_49_09_806427_vehicle.csv'):
            if last_timestamp !=0.0:
                # logging.info(str(msg.timestamp - last_timestamp))
                time.sleep(min(2.0, msg.timestamp - last_timestamp))
            # logging.info(str(msg) + " " + str(i) + " " + )   
            self.bus.send(msg)
            last_timestamp = msg.timestamp
            i+=1
        return

class IDS_timeframe(threading.Thread):
    def __init__(self, group=None, filename=None, target=None, name=None, args=(), kwargs=None, verbose=None):
        super(IDS_timeframe, self).__init__()
        self.target = target
        self.name = name
        self.filename = filename
        return

    def run(self):
        min_tolerance = {}
        # max_tolerance = {}
        last_timestamp = {}
        ignore_next_msg = {}
        logging.debug(self.name + " fired up")
        i = 0

        for msg in CSVReader(self.filename):
            if msg is None:
                logging.info('No message has been received')
                sys.exit()
            else:
                # logging.info(str(msg)+ ' ' + str(i))

                # define threshold of periodicity of the message

                # the arbitration_id  has already been seen
                if msg.dlc != 0 and (msg.arbitration_id not in ignore_next_msg):
                    if msg.arbitration_id in last_timestamp:
                        time_frame = msg.timestamp - last_timestamp[msg.arbitration_id]
                        if msg.arbitration_id not in min_tolerance:
                            min_tolerance[msg.arbitration_id] = time_frame
                        else:
                            if time_frame < (min_tolerance[msg.arbitration_id]/2):
                                logging.error("ATTACK detected: i=" + str(i) + " " + str(msg) + " " + str(time_frame) + " " + str(min_tolerance[msg.arbitration_id]/2))
                                min_tolerance[msg.arbitration_id] = time_frame
                            elif time_frame < min_tolerance[msg.arbitration_id]:
                                min_tolerance[msg.arbitration_id] = time_frame

                    last_timestamp[msg.arbitration_id] = msg.timestamp

                elif msg.dlc != 0 and (msg.arbitration_id in ignore_next_msg):
                    del ignore_next_msg[msg.arbitration_id]
                else:
                    ignore_next_msg[msg.arbitration_id] = True

                # logging.info(msg.arbitration_id)
            i+=1

class IDS_transitions(threading.Thread):
    def __init__(self, tranining_filename=None, detection_filename=None, group=None, target=None, name=None, args=(), kwargs=None, verbose=None):
        super(IDS_transitions, self).__init__()
        self.target = target
        self.name = name
        self.training_filename = tranining_filename
        self.detection_filename = detection_filename
        return

    def run(self):
        i = 0
        transitions = {}
        last_id = 0
        anomaly_counter = 0
        unique_id = {}
        matrix_index = 0

        for msg in CSVReader(self.training_filename):
            # print(transitions)
            if i == 0:
                last_id = msg.arbitration_id
            else:
                if last_id not in transitions:
                    transitions.setdefault(last_id, []).append(msg.arbitration_id)
                else:
                    if msg.arbitration_id not in transitions[last_id]:
                        transitions[last_id].append(msg.arbitration_id)

            last_id = msg.arbitration_id
            # add the id if it was never seen before
            if msg.arbitration_id not in unique_id:
                unique_id[msg.arbitration_id] = matrix_index
                matrix_index+=1
            i+=1
        # print("number of anomalies detected: " + str(anomaly_counter))
        
        # print(transitions)

        print(unique_id)

        #populate matrix
        matrix = [[False for destination in range(len(unique_id))] for origin in range(len(unique_id))]

        for origin in transitions:
            for destination in transitions[origin]:
                matrix[unique_id[origin]][unique_id[destination]] = True
        
        # print(matrix)

        i = 0
        anomaly_counter = 0
        for msg in CSVReader(self.detection_filename):
            
            # if i != 0:
            #     if last_id in transitions:
            #         if msg.arbitration_id not in transitions[last_id]:
            #             logging.info("ANOMALY detected in transition: " + str(last_id) + " -> " + str(msg.arbitration_id))
            #             anomaly_counter += 1
            #     else:
            #         logging.info("ANOMALY detected in transition: " + str(last_id) + " -> " + str(msg.arbitration_id))
            #         anomaly_counter += 1
            if i != 0:
                if last_id not in unique_id and msg.arbitration_id not in unique_id:
                    # logging.info("ANOMALY detected in transition: " + str(last_id) + " -> " + str(msg.arbitration_id))
                    anomaly_counter += 1
                else:
                    if not matrix[unique_id[last_id]][unique_id[msg.arbitration_id]]:
                        # logging.info("ANOMALY detected in transition: " + str(last_id) + " -> " + str(msg.arbitration_id))
                        anomaly_counter += 1
            
            i+=1
            last_id = msg.arbitration_id
        print("number of anomalies detected: " + str(anomaly_counter))

        print("transitions", len(transitions))
        print("unique id", len(unique_id))

if __name__ == '__main__':

    filenames = [
        '/home/alright/TURKU/thesis/data/ReCAN/alfa_romeo/raw33.csv',
        '/home/alright/TURKU/thesis/data/ReCAN/alfa_romeo/raw11.csv',
        '/home/alright/TURKU/thesis/data/ReCAN/alfa_romeo/raw22.csv',
        '/home/alright/TURKU/thesis/data/CAN-Vehicle/2020_12_04_15_49_09_806427_vehicle.csv',
        '/home/alright/TURKU/thesis/data/OTIDS/Fuzzy_attack_dataset1.txt',
        '/home/alright/TURKU/thesis/data/OTIDS/Attack_free_dataset1.txt',
        '/home/alright/TURKU/thesis/data/CAN-Vehicle/2020_12_07_07_54_05_363774_vehicle.csv'
    ]
    logging.debug('Bus initialization')

    ids_timeframe = IDS_timeframe(
        name='ids_timeframe', 
        
        filename=filenames[0])
    logging.debug(ids_timeframe.name + ' initialized')

    # start threads
    ids_timeframe.start()
    ids_transitions = IDS_transitions(
        name='ids_transitions', 
        tranining_filename=filenames[1], 
        detection_filename=filenames[2])
    ids_transitions.start()
    # CANbus.start()
