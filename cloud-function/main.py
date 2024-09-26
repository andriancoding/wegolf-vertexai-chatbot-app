from google.cloud import functions_v1
from supabase import create_client, Client
from datetime import datetime, timedelta
import os, json
from flask import jsonify 
import functions_framework

# Supabase configuration
supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(supabase_url, supabase_key)

@functions_framework.http
def handle_request(request):
    """
    This function handles incoming HTTP requests for booking and cancellation actions. 
    It supports CORS preflight requests and processes POST requests based on the fulfillment tag from Dialogflow CX. 
    The function delegates the logic to either `new_booking` or `cancel_booking` based on the tag, and formats the response accordingly.

    Args:
        request (flask.Request): The HTTP request object from Dialogflow CX.

    Returns:
        tuple: A JSON response with the fulfillment message, HTTP status code, and headers for CORS.
    """
    # Handle CORS preflight request
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Content-Type',
        }
        return ('', 204, headers)

    try:
        if request.method == "POST":
            req = request.get_json()
            tag = req['fulfillmentInfo']['tag']
            if tag == 'makeNewBooking':
                response_text = new_booking(req)
            elif tag == "cancelBooking":
                response_text = cancel_booking(req) 
            else:
                response_text = "Unsupported request content"
    except Exception as e:
        print(f"handle_request: {e}")
        response_text = "Something went wrong while processing your request. Please try again later."
    
    print(f"response_text: {response_text}")
    # Prepare and return the response to Dialogflow CX
    fulfillment_response = {
        "fulfillment_response": {
            "messages": [
                {
                    "text": {
                        "text": [response_text]
                    }
                }
            ]
        }
    }
    # Return response
    headers = {'Access-Control-Allow-Origin': '*'}
    return jsonify(fulfillment_response), 200, headers

def cancel_booking(request):
    """
    This function cancels an existing booking in the Supabase database based on the booking ID and customer email 
    provided in the request.

    Args:
        request (dict): The request payload containing booking ID and customer email.

    Returns:
        str: A response message indicating whether the booking was successfully canceled or not.
    """
    try:
        data = request['sessionInfo']['parameters']
        print(data)
        booking_id = int(data['booking_id'])
        customer_email = str(data['customer_email']).lower()

        response = supabase.table('bookings').update({'status': "cancelled"}).eq("id", booking_id).eq('email', customer_email).execute()
        if response.data:
            response_text = "Your booking has been cancelled!"
        else:
            response_text = "No booking found with the given id and email"
        return response_text
    except Exception as e:
        print(f"cancel_booking: {e}")
        return "Something went wrong, when trying to cancel your booking. Please try again later"

def new_booking(request):
    """
    This function processes new booking requests. It calculates available time slots, assigns a bay, 
    and inserts the booking details into the Supabase database.

    Args:
        request (dict): The request payload containing booking parameters such as date, start time, 
                        duration, and customer email.

    Returns:
        str: A response message indicating whether the booking was successfully made or not.
    """
    try:
        data = request['sessionInfo']['parameters']
        print(data)
        duration = data['booking_duration'].split(' ')[0]
        booking_date = f"{int(data['booking_date']['year'])}-{int(data['booking_date']['month'])}-{int(data['booking_date']['day'])}"
        start_time = format_start_time(data['booking_start_time'])
        end_time = generate_end_time(duration, start_time)
        bay_id = find_a_bay(booking_date, start_time, end_time)

        if bay_id is None:
            response_text = "No bays are available for the selected time."
        else:
            response = supabase.table('bookings').insert({
                'email': data['customer_email'],
                'bay_id': bay_id,
                'date': booking_date,
                'start_time': start_time,
                'end_time': end_time,
                'status': "booked",
                'duration': duration
            }).execute()
            print(response)
            if response.data:
                booking_info = response.data[0]
                response_text = f'''
                    Booking successfully made! 
                    Booking number: {booking_info['id']} 
                    Assigned bay: {booking_info['bay_id']} 
                    See you on {booking_info['date']} !!
                '''
            else:
                response_text = "There was an error processing your booking."
        return response_text
    except Exception as e:
        print(f"new_booking: {e}")
        return "Something went wrong, when trying to make your booking. Please try again later"

def find_a_bay(booking_date, start_time, end_time):
    """
    This function checks the availability of bays for a given booking time slot. 
    It queries the Supabase database to find available bays that do not overlap with existing bookings.

    Args:
        booking_date (str): The date of the booking in 'YYYY-MM-DD' format.
        start_time (str): The start time of the booking in 'HH:MM:SS' format.
        end_time (str): The end time of the booking in 'HH:MM:SS' format.

    Returns:
        int: The ID of the available bay, or None if no bays are available.
    """
    try:
        booked_bays = supabase.table('bookings').select('bay_id').eq('date', booking_date).lt("start_time", end_time).gt("end_time", start_time).execute()
        booked_bay_ids = [bay['bay_id'] for bay in booked_bays.data]

        if booked_bay_ids:
            available_bays = supabase.table('bays').select('id').not_.in_('id', booked_bay_ids).eq('status', 'Available').execute()
            available_bay_ids = [bay['id'] for bay in available_bays.data]
            return available_bay_ids[0] if available_bay_ids else None
        else:
            available_bays = supabase.table('bays').select('id').execute()
            available_bay_ids = [bay['id'] for bay in available_bays.data]
            return available_bay_ids[0] if available_bay_ids else None
    except Exception as e:
        print(f"find_a_bay: {e}")
        return None

def generate_end_time(duration, start_time):
    """
    This function calculates the end time of a booking based on its start time and duration.

    Args:
        duration (str): The duration of the booking in hours.
        start_time (str): The start time of the booking in 'HH:MM:SS' format.

    Returns:
        str: The end time of the booking in 'HH:MM:SS' format, or None if there's an error.
    """
    try:
        start_time = datetime.strptime(start_time, '%H:%M:%S')
        duration = timedelta(hours=int(duration))
        end_time = (start_time + duration).time().strftime('%H:%M:%S')
        return end_time
    except Exception as e:
        print(f"generate_end_time: {e}")
        return None

def format_start_time(start_time):
    """
    This function converts the start time from 12-hour format (with AM/PM) to 24-hour format ('HH:MM:SS').

    Args:
        start_time (str): The start time in 12-hour format (e.g., '02:00 PM').

    Returns:
        str: The formatted start time in 24-hour format ('HH:MM:SS'), or None if there's an error.
    """
    try:
        formatted_start_time = datetime.strptime(start_time, '%I:%M %p').strftime('%H:%M:%S')
        return formatted_start_time
    except Exception as e:
        print(f"format_start_time: {e}")
        return None
