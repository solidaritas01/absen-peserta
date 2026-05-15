document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    loadParticipants();

    // Form handlers
    document.getElementById('form-masuk').addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = document.getElementById('search-name-masuk').value;
        await submitAttendance(name, 'Hadir');
    });

    document.getElementById('form-izin').addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = document.getElementById('search-name-izin').value;
        const reason = document.getElementById('reason-izin').value;
        await submitAttendance(name, 'Izin', reason);
    });
});

async function loadSettings() {
    try {
        const response = await fetch(`/api/settings?user_id=${targetUserId}`);
        const data = await response.json();
        
        document.getElementById('display-activity-name').textContent = data.activity_name;
        document.getElementById('display-schedule').textContent = new Date(data.activity_schedule).toLocaleString('id-ID', {
            weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });

        applyTheme(data);

        if (data.logos && data.logos.length > 0) {
            const logoHtml = data.logos.map(filename => `<img src="/static/uploads/${filename}" alt="Logo" style="height: 80px; object-fit: contain;">`).join('');
            document.getElementById('display-logo').innerHTML = logoHtml;
        }
    } catch (err) {
        console.error('Error loading settings:', err);
    }
}

async function loadParticipants() {
    try {
        const response = await fetch(`/api/participants?user_id=${targetUserId}`);
        const participants = await response.json();
        
        const datalist = document.getElementById('participant-list');
        datalist.innerHTML = '';
        
        // Filter only those who haven't checked in
        const available = participants.filter(p => p.status === 'Tidak/Belum Hadir');
        
        available.forEach(p => {
            const option = document.createElement('option');
            option.value = p.name;
            datalist.appendChild(option);
        });
    } catch (err) {
        console.error('Error loading participants:', err);
    }
}

async function submitAttendance(name, status, reason = '') {
    try {
        const response = await fetch('/api/attendance', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                name, 
                status, 
                reason, 
                user_id: targetUserId 
            })
        });
        
        const result = await response.json();
        if (result.status === 'success') {
            showModal(status, result.attendance_status);
            // Reset forms and reload participant list (which removes the name)
            document.getElementById('form-masuk').reset();
            document.getElementById('form-izin').reset();
            loadParticipants();
        }
    } catch (err) {
        console.error('Error submitting attendance:', err);
    }
}

function switchTab(tab) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    
    document.getElementById(`tab-${tab}`).classList.add('active');
    document.querySelector(`button[onclick="switchTab('${tab}')"]`).classList.add('active');
}

function showModal(type, finalStatus) {
    const modal = document.getElementById('modal-success');
    const title = document.getElementById('modal-title');
    const msg = document.getElementById('modal-message');
    
    if (type === 'Hadir') {
        title.textContent = 'Selamat Datang!';
        msg.textContent = finalStatus === 'Terlambat' 
            ? 'Presensi berhasil dicatat (Terlambat). Silakan masuk ke ruangan.'
            : 'Presensi berhasil dicatat (Tepat Waktu). Selamat berkegiatan!';
    } else {
        title.textContent = 'Berhasil Terkirim';
        msg.textContent = 'Data izin anda telah kami terima. Terima kasih.';
    }
    
    modal.style.display = 'flex';
}

function closeModal() {
    document.getElementById('modal-success').style.display = 'none';
}

function applyTheme(data) {
    document.body.className = ''; // Reset
    const c1 = data.theme_color_1 || '#4f46e5';
    const c2 = data.theme_color_2 || '#06b6d4';
    const type = data.theme_type || 'gradient_animated';
    const preset = data.theme_preset || 'ocean';
    const anim = data.theme_animation || 'flow';

    document.body.style.setProperty('--theme-color-1', c1);
    document.body.style.setProperty('--theme-color-2', c2);
    
    if (type === 'preset') {
        document.body.classList.add(`theme-${preset}`);
    } else {
        document.body.classList.add(`theme-${type}`);
        if (type === 'gradient_animated') {
            document.body.classList.add(`anim-${anim}`);
        }
    }
}
