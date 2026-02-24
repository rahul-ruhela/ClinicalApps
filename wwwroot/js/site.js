// Please see documentation at https://learn.microsoft.com/aspnet/core/client-side/bundling-and-minification
// for details on configuring this project to bundle and minify static web assets.

// Write your JavaScript code.


  function openModal(event) {
            event.preventDefault();
            document.getElementById('userModal').classList.add('active');
            document.body.style.overflow = 'hidden';
        }

        function closeModal() {
            document.getElementById('userModal').classList.remove('active');
            document.body.style.overflow = 'auto';
            document.getElementById('userForm').reset();
            document.querySelectorAll('.form-error').forEach(el => el.classList.remove('show'));
        }

        // Close modal when clicking outside
        document.getElementById('userModal').addEventListener('click', function(e) {
            if (e.target === this) {
                closeModal();
            }
        });

        // Close modal on Escape key
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                closeModal();
            }
        });

        async function submitForm(event) {
            event.preventDefault();

            const name = document.getElementById('userName').value.trim();
            const email = document.getElementById('userEmail').value.trim();
            const submitBtn = document.getElementById('submitBtn');

            // Clear previous errors
            document.querySelectorAll('.form-error').forEach(el => el.classList.remove('show'));

            // Validate
            let hasError = false;
            if (!name) {
                document.getElementById('nameError').classList.add('show');
                hasError = true;
            }
            if (!email || !isValidEmail(email)) {
                document.getElementById('emailError').classList.add('show');
                hasError = true;
            }

            if (hasError) return;

            // Disable button and show loading
            submitBtn.disabled = true;
            submitBtn.textContent = 'Please wait...';

            try {
                const response = await fetch('/api/track-user', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: name,
                        email: email,
                        page: 'index.html',
                        timestamp: new Date().toISOString()
                    })
                });

                if (response.ok) {
                    // Close modal and open demo in new tab
                    closeModal();
                    window.open('/demo', '_blank');
                } else {
                    throw new Error('Failed to submit');
                }
            } catch (error) {
                console.error('Error:', error);
                // Still open the demo even if tracking fails
                closeModal();
                window.open('/demo', '_blank');
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Access Demo';
            }
        }

        function isValidEmail(email) {
            const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            return re.test(email);
}

