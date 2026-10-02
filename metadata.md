Space Study Data Collection
1. Space Profile

Collected once per space.

space_id — assign a unique ID
building — record the official campus name
floor — record the floor
room — record the room number/name
grid_reference — record the location on the floor plan
space_type — select the appropriate space type
seat_count — count the available seats
outlet_count — count the available outlets
outlet_locations — record outlet locations on the floor plan
seating_arrangement — record the main seating arrangement
lighting — record as bright, moderate, or dim
study_signage — record whether study-related signs are present
signage_notes — record the wording or type of signage
networks_available — record available Wi-Fi networks
2. Visit Log

Collected once for every visit.

visit_id — create a unique visit ID
space_id — record the space being visited
date — record the date
day_of_week — record the day
start_time — record when the visit begins
end_time — record when the visit ends
busy_period — classify the space as quiet, moderate, or busy
weather — record the weather during the visit
temperature_c — record the temperature from the same weather source
noise_level — classify the noise level
exam_period — record whether there are major exams or deadlines
exam_notes — record relevant details
semester_week — record the current week of the semester
construction_or_event — record any construction or special event
event_notes — describe the event or construction
food_available — record whether food/coffee is available
food_notes — describe availability if relevant
connection_drops — count network connection drops during the visit
outage_times — record the time of each outage
arrivals — tally people arriving during the visit
departures — tally people leaving during the visit
seats_unused — count unused seats
furniture_moved — count instances of furniture being moved
floor_sitting — count people sitting on the floor
seat_locations — record occupied seat locations on the floor plan
clustering_notes — record noticeable seating clusters
spatial_notes — record other spatial observations
3. Observation Log

Collected three times per visit: at the start, middle, and end.

People

At each observation:

Count the total number of people.
Count people using laptops.
Count people using phones.
Count people using paper/materials.
Count people eating or drinking.
Count people talking.
Record any other relevant category.

A person may be counted in more than one device/material category.

Main Activity

At each observation, assign each person one main activity:

reading
writing
computer work
phone use
conversation
eating
other
Wi-Fi

At each observation:

Record the connected network name.
Record the network type.
Record Wi-Fi signal strength in dBm.
Record the frequency band.
Run the same speed test and record download speed.
Run the same speed test and record upload speed.
Run 20 pings to the same target and record the median latency.
Record packet loss from the 20 pings.
Record cellular signal strength when available.
