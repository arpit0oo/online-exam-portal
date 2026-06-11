function startTimer(seconds, formId) {
    let totalSeconds = seconds;
    const timerDisplay = document.getElementById('timer');
    const form = document.getElementById(formId);
    
    const interval = setInterval(() => {
        totalSeconds--;
        
        const mins = Math.floor(totalSeconds / 60);
        const secs = totalSeconds % 60;
        timerDisplay.textContent = `⏱️ ${mins}:${secs.toString().padStart(2, '0')}`;
        
        // Warning colors
        if (totalSeconds <= 60) {
            timerDisplay.style.background = '#fee2e2';
            timerDisplay.style.color = '#991b1b';
        } else if (totalSeconds <= 300) {
            timerDisplay.style.background = '#fef3c7';
            timerDisplay.style.color = '#92400e';
        }
        
        if (totalSeconds <= 0) {
            clearInterval(interval);
            timerDisplay.textContent = '⏱️ TIME UP!';
            window.onbeforeunload = null; // Clear warning before submitting programmatically
            form.submit();
        }
    }, 1000);
    
    // Prevent accidental navigation
    window.onbeforeunload = function() {
        return "You have an ongoing exam. Are you sure you want to leave?";
    };
    
    // Remove warning on form submit
    form.addEventListener('submit', () => {
        window.onbeforeunload = null;
    });
}
