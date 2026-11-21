"""Translations for transactional email content (5 languages).

Keys:
- subject: email subject line
- greeting: header line
- body: introductory paragraph (HTML allowed)
- action: instruction before CTA button
- button: CTA button label
- footer: link fallback line
- auto_gen: footer disclaimer
"""

from typing import TypedDict

from app.i18n._types import Language


class RegistrationEmailContent(TypedDict):
    """Type definition for registration email content dictionary."""

    subject: str
    greeting: str
    body: str
    action: str
    button: str
    footer: str
    auto_gen: str


class InvitationEmailContent(TypedDict):
    """Type definition for the organization-invitation email content."""

    subject: str
    greeting: str
    body: str
    role_line: str
    action: str
    button: str
    footer: str
    expiry: str
    auto_gen: str
    roles: dict[str, str]


class PasswordResetEmailContent(TypedDict):
    """Type definition for password-reset email content dictionary."""

    subject: str
    greeting: str
    body: str
    action: str
    button: str
    footer: str
    expiry: str
    auto_gen: str


REGISTRATION_EMAIL_CONTENT: dict[Language, RegistrationEmailContent] = {
    'en': {
        'subject': 'Your access to Inventari has been approved!',
        'greeting': 'Hello!',
        'body': 'Good news! Your request for access to the <b>Inventari</b> system has been approved by the administrator.',
        'action': 'Click the button below to complete your registration and set your password:',
        'button': 'Complete Registration',
        'footer': "If the button doesn't work, copy and paste this link into your browser:",
        'auto_gen': 'This is an automatically generated message from Inventari.',
    },
    'pl': {
        'subject': 'Twój dostęp do Inventari został zatwierdzony!',
        'greeting': 'Witaj!',
        'body': 'Mamy dobrą wiadomość! Twoja prośba o dostęp do systemu <b>Inventari</b> została zatwierdzona przez administratora.',
        'action': 'Kliknij w poniższy przycisk, aby dokończyć rejestrację i skonfigurować swoje hasło:',
        'button': 'Dokończ rejestrację',
        'footer': 'Jeśli przycisk nie działa, skopiuj i wklej ten link do przeglądarki:',
        'auto_gen': 'Wiadomość wygenerowana automatycznie przez system Inventari.',
    },
    'de': {
        'subject': 'Ihr Zugang zu Inventari wurde genehmigt!',
        'greeting': 'Hallo!',
        'body': 'Gute Nachrichten! Ihre Zugriffsanfrage auf das System <b>Inventari</b> wurde vom Administrator genehmigt.',
        'action': 'Klicken Sie auf die Schaltfläche unten, um Ihre Registrierung abzuschließen und Ihr Passwort festzulegen:',
        'button': 'Registrierung abschließen',
        'footer': 'Falls die Schaltfläche nicht funktioniert, kopieren Sie diesen Link in Ihren Browser:',
        'auto_gen': 'Dies ist eine automatisch generierte Nachricht von Inventari.',
    },
    'fr': {
        'subject': 'Votre accès à Inventari a été approuvé !',
        'greeting': 'Bonjour !',
        'body': "Bonne nouvelle ! Votre demande d'accès au système <b>Inventari</b> a été approuvée par l'administrateur.",
        'action': 'Cliquez sur le bouton ci-dessous pour finaliser votre inscription et définir votre mot de passe :',
        'button': "Finaliser l'inscription",
        'footer': 'Si le bouton ne fonctionne pas, copiez-collez ce lien dans votre navigateur :',
        'auto_gen': 'Ceci est un message généré automatiquement par Inventari.',
    },
    'es': {
        'subject': '¡Tu acceso a Inventari ha sido aprobado!',
        'greeting': '¡Hola!',
        'body': '¡Buenas noticias! Tu solicitud de acceso al sistema <b>Inventari</b> ha sido aprobada por el administrador.',
        'action': 'Haz clic en el botón de abajo para completar tu registro y establecer tu contraseña:',
        'button': 'Completar registro',
        'footer': 'Si el botón no funciona, copia y pega este enlace en tu navegador:',
        'auto_gen': 'Este es un mensaje generado automáticamente por Inventari.',
    },
    'pt': {
        'subject': 'Seu acesso ao Inventari foi aprovado!',
        'greeting': 'Olá!',
        'body': 'Boas notícias! Sua solicitação de acesso ao sistema <b>Inventari</b> foi aprovada pelo administrador.',
        'action': 'Clique no botão abaixo para concluir seu cadastro e definir sua senha:',
        'button': 'Concluir cadastro',
        'footer': 'Se o botão não funcionar, copie e cole este link no seu navegador:',
        'auto_gen': 'Esta é uma mensagem gerada automaticamente pelo Inventari.',
    },
}


def get_registration_email_content(lang: str) -> RegistrationEmailContent:
    """Return registration email content for *lang*, falling back to English."""
    if lang in REGISTRATION_EMAIL_CONTENT:
        return REGISTRATION_EMAIL_CONTENT[lang]  # type: ignore[index]
    return REGISTRATION_EMAIL_CONTENT['en']


PASSWORD_RESET_EMAIL_CONTENT: dict[Language, PasswordResetEmailContent] = {
    'en': {
        'subject': 'Reset your Inventari password',
        'greeting': 'Hello!',
        'body': 'We received a request to reset the password for your <b>Inventari</b> account.',
        'action': 'Click the button below to choose a new password:',
        'button': 'Reset password',
        'footer': "If the button doesn't work, copy and paste this link into your browser:",
        'expiry': 'This link expires in 30 minutes. If you did not request a reset, you can safely ignore this email.',
        'auto_gen': 'This is an automatically generated message from Inventari.',
    },
    'pl': {
        'subject': 'Zresetuj swoje hasło do Inventari',
        'greeting': 'Witaj!',
        'body': 'Otrzymaliśmy prośbę o zresetowanie hasła do Twojego konta <b>Inventari</b>.',
        'action': 'Kliknij poniższy przycisk, aby ustawić nowe hasło:',
        'button': 'Zresetuj hasło',
        'footer': 'Jeśli przycisk nie działa, skopiuj i wklej ten link do przeglądarki:',
        'expiry': 'Link jest ważny przez 30 minut. Jeśli nie prosiłeś o reset, możesz zignorować tę wiadomość.',
        'auto_gen': 'Wiadomość wygenerowana automatycznie przez system Inventari.',
    },
    'de': {
        'subject': 'Setzen Sie Ihr Inventari-Passwort zurück',
        'greeting': 'Hallo!',
        'body': 'Wir haben eine Anfrage zum Zurücksetzen des Passworts für Ihr <b>Inventari</b>-Konto erhalten.',
        'action': 'Klicken Sie auf die Schaltfläche unten, um ein neues Passwort festzulegen:',
        'button': 'Passwort zurücksetzen',
        'footer': 'Falls die Schaltfläche nicht funktioniert, kopieren Sie diesen Link in Ihren Browser:',
        'expiry': 'Dieser Link ist 30 Minuten gültig. Wenn Sie das Zurücksetzen nicht angefordert haben, können Sie diese E-Mail ignorieren.',
        'auto_gen': 'Dies ist eine automatisch generierte Nachricht von Inventari.',
    },
    'fr': {
        'subject': 'Réinitialisez votre mot de passe Inventari',
        'greeting': 'Bonjour !',
        'body': 'Nous avons reçu une demande de réinitialisation du mot de passe de votre compte <b>Inventari</b>.',
        'action': 'Cliquez sur le bouton ci-dessous pour choisir un nouveau mot de passe :',
        'button': 'Réinitialiser le mot de passe',
        'footer': 'Si le bouton ne fonctionne pas, copiez-collez ce lien dans votre navigateur :',
        'expiry': "Ce lien expire dans 30 minutes. Si vous n'êtes pas à l'origine de cette demande, vous pouvez ignorer cet e-mail.",
        'auto_gen': 'Ceci est un message généré automatiquement par Inventari.',
    },
    'es': {
        'subject': 'Restablece tu contraseña de Inventari',
        'greeting': '¡Hola!',
        'body': 'Recibimos una solicitud para restablecer la contraseña de tu cuenta de <b>Inventari</b>.',
        'action': 'Haz clic en el botón de abajo para elegir una nueva contraseña:',
        'button': 'Restablecer contraseña',
        'footer': 'Si el botón no funciona, copia y pega este enlace en tu navegador:',
        'expiry': 'Este enlace caduca en 30 minutos. Si no solicitaste el restablecimiento, puedes ignorar este correo.',
        'auto_gen': 'Este es un mensaje generado automáticamente por Inventari.',
    },
    'pt': {
        'subject': 'Redefina sua senha do Inventari',
        'greeting': 'Olá!',
        'body': 'Recebemos uma solicitação para redefinir a senha da sua conta do <b>Inventari</b>.',
        'action': 'Clique no botão abaixo para escolher uma nova senha:',
        'button': 'Redefinir senha',
        'footer': 'Se o botão não funcionar, copie e cole este link no seu navegador:',
        'expiry': 'Este link expira em 30 minutos. Se você não solicitou a redefinição, pode ignorar este e-mail com segurança.',
        'auto_gen': 'Esta é uma mensagem gerada automaticamente pelo Inventari.',
    },
}


def get_password_reset_email_content(lang: str) -> PasswordResetEmailContent:
    """Return password-reset email content for *lang*, falling back to English."""
    if lang in PASSWORD_RESET_EMAIL_CONTENT:
        return PASSWORD_RESET_EMAIL_CONTENT[lang]  # type: ignore[index]
    return PASSWORD_RESET_EMAIL_CONTENT['en']


INVITATION_EMAIL_CONTENT: dict[Language, InvitationEmailContent] = {
    'en': {
        'subject': 'You have been invited to {organization}',
        'greeting': 'You have been invited!',
        'body': 'An administrator has invited you to join <b>{organization}</b> in Inventari.',
        'role_line': 'Your role: <b>{role}</b>',
        'action': 'Click the button below to accept the invitation:',
        'button': 'Accept invitation',
        'footer': "If the button doesn't work, copy and paste this link into your browser:",
        'expiry': 'This invitation is valid for 7 days and can only be accepted from this email address.',
        'auto_gen': 'This is an automatically generated message from Inventari.',
        'roles': {
            'admin': 'Administrator',
            'manager': 'Manager',
            'user': 'User',
            'viewer': 'Viewer',
        },
    },
    'pl': {
        'subject': 'Zaproszenie do organizacji {organization}',
        'greeting': 'Masz zaproszenie!',
        'body': 'Administrator zaprasza Cię do organizacji <b>{organization}</b> w systemie Inventari.',
        'role_line': 'Twoja rola: <b>{role}</b>',
        'action': 'Kliknij w poniższy przycisk, aby przyjąć zaproszenie:',
        'button': 'Przyjmij zaproszenie',
        'footer': 'Jeśli przycisk nie działa, skopiuj i wklej ten link do przeglądarki:',
        'expiry': 'Zaproszenie jest ważne 7 dni i można je przyjąć wyłącznie z tego adresu e-mail.',
        'auto_gen': 'Wiadomość wygenerowana automatycznie przez system Inventari.',
        'roles': {
            'admin': 'Administrator',
            'manager': 'Menedżer',
            'user': 'Użytkownik',
            'viewer': 'Obserwator',
        },
    },
    'de': {
        'subject': 'Sie wurden zu {organization} eingeladen',
        'greeting': 'Sie wurden eingeladen!',
        'body': 'Ein Administrator lädt Sie ein, der Organisation <b>{organization}</b> in Inventari beizutreten.',
        'role_line': 'Ihre Rolle: <b>{role}</b>',
        'action': 'Klicken Sie auf die Schaltfläche unten, um die Einladung anzunehmen:',
        'button': 'Einladung annehmen',
        'footer': 'Falls die Schaltfläche nicht funktioniert, kopieren Sie diesen Link in Ihren Browser:',
        'expiry': 'Diese Einladung ist 7 Tage gültig und kann nur mit dieser E-Mail-Adresse angenommen werden.',
        'auto_gen': 'Dies ist eine automatisch generierte Nachricht von Inventari.',
        'roles': {
            'admin': 'Administrator',
            'manager': 'Manager',
            'user': 'Benutzer',
            'viewer': 'Betrachter',
        },
    },
    'fr': {
        'subject': 'Vous avez été invité à rejoindre {organization}',
        'greeting': 'Vous avez été invité !',
        'body': "Un administrateur vous invite à rejoindre l'organisation <b>{organization}</b> dans Inventari.",
        'role_line': 'Votre rôle : <b>{role}</b>',
        'action': "Cliquez sur le bouton ci-dessous pour accepter l'invitation :",
        'button': "Accepter l'invitation",
        'footer': 'Si le bouton ne fonctionne pas, copiez-collez ce lien dans votre navigateur :',
        'expiry': "Cette invitation est valable 7 jours et ne peut être acceptée qu'avec cette adresse e-mail.",
        'auto_gen': 'Ceci est un message généré automatiquement par Inventari.',
        'roles': {
            'admin': 'Administrateur',
            'manager': 'Gestionnaire',
            'user': 'Utilisateur',
            'viewer': 'Observateur',
        },
    },
    'es': {
        'subject': 'Te han invitado a {organization}',
        'greeting': '¡Te han invitado!',
        'body': 'Un administrador te invita a unirte a <b>{organization}</b> en Inventari.',
        'role_line': 'Tu rol: <b>{role}</b>',
        'action': 'Haz clic en el botón de abajo para aceptar la invitación:',
        'button': 'Aceptar invitación',
        'footer': 'Si el botón no funciona, copia y pega este enlace en tu navegador:',
        'expiry': 'Esta invitación es válida durante 7 días y solo se puede aceptar desde esta dirección de correo.',
        'auto_gen': 'Este es un mensaje generado automáticamente por Inventari.',
        'roles': {
            'admin': 'Administrador',
            'manager': 'Gerente',
            'user': 'Usuario',
            'viewer': 'Observador',
        },
    },
    'pt': {
        'subject': 'Você foi convidado para {organization}',
        'greeting': 'Você recebeu um convite!',
        'body': 'Um administrador convidou você para participar de <b>{organization}</b> no Inventari.',
        'role_line': 'Sua função: <b>{role}</b>',
        'action': 'Clique no botão abaixo para aceitar o convite:',
        'button': 'Aceitar convite',
        'footer': 'Se o botão não funcionar, copie e cole este link no seu navegador:',
        'expiry': 'Este convite é válido por 7 dias e só pode ser aceito a partir deste endereço de e-mail.',
        'auto_gen': 'Esta é uma mensagem gerada automaticamente pelo Inventari.',
        'roles': {
            'admin': 'Administrador',
            'manager': 'Gerente',
            'user': 'Usuário',
            'viewer': 'Visualizador',
        },
    },
}


def get_invitation_email_content(lang: str) -> InvitationEmailContent:
    """Return invitation email content for *lang*, falling back to English."""
    if lang in INVITATION_EMAIL_CONTENT:
        return INVITATION_EMAIL_CONTENT[lang]  # type: ignore[index]
    return INVITATION_EMAIL_CONTENT['en']
