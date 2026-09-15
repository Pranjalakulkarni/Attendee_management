document.addEventListener('DOMContentLoaded', () => {
    const attendeeList = document.getElementById('attendee-list');
    const API_BASE_URL = 'http://localhost:8000/api';

    // Function to render a single attendee
    const renderAttendee = (attendee) => {
        // Use a unique ID for each attendee's element
        const attendeeId = `attendee-${attendee.id}`;
        let attendeeEl = document.getElementById(attendeeId);

        // Create the element if it doesn't exist
        if (!attendeeEl) {
            attendeeEl = document.createElement('div');
            attendeeEl.id = attendeeId;
            attendeeEl.className = 'attendee-item';
        }

        // Determine button text and action based on checked_in status
        const buttonAction = attendee.checked_in ? 'checkout' : 'checkin';
        const buttonText = attendee.checked_in ? 'Check Out' : 'Check In';
        const buttonClass = attendee.checked_in ? 'checkout-btn' : 'checkin-btn';

        // Update the content of the attendee element
        attendeeEl.innerHTML = `
            <div class="info">
                <span class="name">${attendee.name}</span>
                <span class="email">${attendee.email}</span>
                <span class="status">Status: ${attendee.status}</span>
            </div>
            <div class="actions">
                <button class="${buttonClass}" data-id="${attendee.id}" data-action="${buttonAction}">
                    ${buttonText}
                </button>
            </div>
        `;

        // Prepend to the list if it's a new item, otherwise it's already in place
        if (!document.getElementById(attendeeId)) {
            attendeeList.prepend(attendeeEl);
        }
    };

    // Function to fetch all attendees and render them
    const fetchAndRenderAttendees = async () => {
        try {
            const response = await fetch(`${API_BASE_URL}/attendees`);
            if (!response.ok) throw new Error('Failed to fetch attendees');
            const attendees = await response.json();
            attendeeList.innerHTML = ''; // Clear the list before re-rendering
            attendees.forEach(renderAttendee);
        } catch (error) {
            console.error('Error fetching attendees:', error);
            attendeeList.innerHTML = '<p>Error loading attendees.</p>';
        }
    };

    // Handle button clicks for check-in and check-out
    attendeeList.addEventListener('click', async (event) => {
        const button = event.target.closest('button');
        if (!button) return;

        const attendeeId = button.dataset.id;
        const action = button.dataset.action;

        if (!attendeeId || !action) return;

        try {
            const response = await fetch(`${API_BASE_URL}/${action}/${attendeeId}`, {
                method: 'POST',
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || `Failed to ${action}`);
            }
            // The WebSocket will handle the UI update, so no need to do anything here.
        } catch (error) {
            console.error(`Error during ${action}:`, error);
            alert(`Could not ${action} attendee: ${error.message}`);
        }
    });

    // Set up WebSocket connection for real-time updates
    const setupWebSocket = () => {
        const ws = new WebSocket('ws://localhost:8000/ws/checkins');

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.attendee) {
                // Re-render the specific attendee that was updated
                renderAttendee(data.attendee);
            }
        };

        ws.onclose = () => setTimeout(setupWebSocket, 3000); // Reconnect on close
    };

    // Initial load and WebSocket setup
    fetchAndRenderAttendees();
    setupWebSocket();
});