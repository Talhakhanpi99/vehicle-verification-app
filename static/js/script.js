// Format placeholder functionality
document.addEventListener('DOMContentLoaded', function() {
    // Handle format placeholders
    const formatInputs = document.querySelectorAll('.format-placeholder');
    
    formatInputs.forEach(input => {
        const placeholderText = input.getAttribute('placeholder');
        
        input.addEventListener('focus', function() {
            this.placeholder = '';
        });
        
        input.addEventListener('blur', function() {
            if (this.value === '') {
                this.placeholder = placeholderText;
            }
        });
    });

    // Smooth scrolling (not used in current design but kept for reference)
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            document.querySelector(this.getAttribute('href')).scrollIntoView({
                behavior: 'smooth'
            });
        });
    });
});
