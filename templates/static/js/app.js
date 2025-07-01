document.addEventListener('DOMContentLoaded', () => {
    // --- DOM Elemente ---
    const calendarGrid = document.getElementById('calendar-grid');
    const monthYearEl = document.getElementById('month-year');
    const prevMonthBtn = document.getElementById('prev-month');
    const nextMonthBtn = document.getElementById('next-month');
    const chatWindow = document.getElementById('chat-window');
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const sendButton = document.getElementById('send-button');
    const briefingPanel = document.getElementById('briefing-content');
    const typingIndicator = document.getElementById('typing-indicator');

    // --- State ---
    let currentDate = new Date();
    let activeDays = [];
    let selectedDate = new Date().toISOString().split('T')[0];
    let isChatting = false;

    // --- Initialisierung ---
    const init = async () => {
        await fetchActiveDays();
        renderCalendar();
        loadInitialStateForToday();

        if (missedDayPrompt) {
            displayMessage('lumi', missedDayPrompt);
            chatInput.value = "Ich erzähl dir kurz, was los war...";
            chatInput.focus();
        }
    };

    // --- Kalender-Funktionen ---
    const renderCalendar = () => {
        calendarGrid.innerHTML = '';
        const year = currentDate.getFullYear();
        const month = currentDate.getMonth();

        monthYearEl.textContent = `${currentDate.toLocaleString('de-DE', { month: 'long' })} ${year}`;

        const firstDay = new Date(year, month, 1);
        const lastDay = new Date(year, month + 1, 0);
        const daysInMonth = lastDay.getDate();

        const weekdays = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
        weekdays.forEach(day => {
            const dayEl = document.createElement('div');
            dayEl.className = 'font-bold text-sm text-gray-500';
            dayEl.textContent = day;
            calendarGrid.appendChild(dayEl);
        });

        const startOffset = (firstDay.getDay() + 6) % 7;
        for (let i = 0; i < startOffset; i++) {
            calendarGrid.appendChild(document.createElement('div'));
        }

        for (let day = 1; day <= daysInMonth; day++) {
            const dayEl = document.createElement('div');
            const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;

            dayEl.textContent = day;
            dayEl.className = 'calendar-day w-8 h-8 flex items-center justify-center cursor-pointer hover:bg-green-100 rounded-full';
            dayEl.dataset.date = dateStr;

            if (activeDays.includes(dateStr)) {
                dayEl.classList.add('active');
            }
            if (dateStr === new Date().toISOString().split('T')[0]) {
                dayEl.classList.add('today');
            }
            if (dateStr === selectedDate) {
                dayEl.classList.add('selected');
            }

            dayEl.addEventListener('click', () => handleDateClick(dateStr));
            calendarGrid.appendChild(dayEl);
        }
    };

    const fetchActiveDays = async () => {
        const response = await fetch('/api/active_dates');
        activeDays = await response.json();
    };

    const handleDateClick = async (dateStr) => {
        selectedDate = dateStr;
        isChatting = false;
        renderCalendar();
        chatWindow.innerHTML = '';
        briefingPanel.innerHTML = '<p class="text-gray-400">Lade Daten...</p>';

        const isToday = (dateStr === new Date().toISOString().split('T')[0]);
        chatInput.disabled = !isToday;
        sendButton.disabled = !isToday;
        chatInput.placeholder = isToday ? "Erzähl LUMI, was du heute gelernt hast..." : "Einträge sind nur für den heutigen Tag möglich.";

        const response = await fetch(`/api/entry_for_date?date=${dateStr}`);
        const data = await response.json();

        data.chat.forEach(msg => displayMessage(msg.sender, msg.message));
        updateBriefingPanel(data.briefing);

        // Wenn heute, aber noch kein Chat, besondere Nachricht anzeigen
        if (isToday && data.chat.length === 0) {
            briefingPanel.innerHTML = '<p class="text-gray-400">Starte einen neuen Eintrag, um das Briefing hier zu sehen.</p>';
        }
    };

    const loadInitialStateForToday = () => {
        handleDateClick(new Date().toISOString().split('T')[0]);
    }

    prevMonthBtn.addEventListener('click', () => {
        currentDate.setMonth(currentDate.getMonth() - 1);
        renderCalendar();
    });

    nextMonthBtn.addEventListener('click', () => {
        currentDate.setMonth(currentDate.getMonth() + 1);
        renderCalendar();
    });

    // --- Chat-Funktionen ---
    const handleChatSubmit = async (e) => {
        e.preventDefault();
        const message = chatInput.value.trim();
        if (!message || isChatting) return;

        isChatting = true;
        setUiLoading(true);
        displayMessage('user', message);
        chatInput.value = '';

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message, date: selectedDate })
            });
            const data = await response.json();

            displayMessage('lumi', data.reply);
            if (data.briefing) {
                updateBriefingPanel(data.briefing);
                // Chat beendet, keine weiteren Eingaben für heute
                chatInput.placeholder = "Super gemacht für heute! Bis morgen!";
                chatInput.disabled = true;
                sendButton.disabled = true;
            } else {
                 isChatting = false;
            }
        } catch (error) {
            console.error("Chat Error:", error);
            displayMessage('lumi', 'Ups, da ist etwas schiefgelaufen. Bitte versuche es erneut.');
            isChatting = false;
        } finally {
             setUiLoading(false);
        }
    };

    const displayMessage = (sender, text) => {
        const bubble = document.createElement('div');
        bubble.className = `chat-bubble p-3 rounded-2xl ${sender}`;
        bubble.innerHTML = text.replace(/\n/g, '<br>'); // Zeilenumbrüche erhalten
        chatWindow.appendChild(bubble);
        chatWindow.scrollTop = chatWindow.scrollHeight;
    };

    const setUiLoading = (isLoading) => {
        chatInput.disabled = isLoading;
        sendButton.disabled = isLoading;
        typingIndicator.style.display = isLoading ? 'block' : 'none';
        if (isLoading) {
             chatWindow.scrollTop = chatWindow.scrollHeight;
        }
    };

    chatForm.addEventListener('submit', handleChatSubmit);

    // --- Briefing-Funktionen ---
    const updateBriefingPanel = (briefingText) => {
        if (briefingText && briefingText.trim() !== '') {
            // Markdown-ähnliche Formatierung in HTML umwandeln
            let formattedHtml = briefingText
                .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>') // Fett
                .replace(/- (.*?):/g, '<br><strong>$1:</strong>') // List items
                .replace(/\n/g, '<br>');
            if (formattedHtml.startsWith('<br>')) {
                formattedHtml = formattedHtml.substring(4);
            }
            briefingPanel.innerHTML = formattedHtml;
        } else {
            const isToday = (selectedDate === new Date().toISOString().split('T')[0]);
            briefingPanel.innerHTML = `<p class="text-gray-400">${isToday ? "Das Briefing erscheint hier, sobald dein Gespräch mit LUMI abgeschlossen ist." : "Für diesen Tag gibt es kein Briefing."}</p>`;
        }
    };

    // --- Start der App ---
    init();
});