from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from flask_login import UserMixin

db = SQLAlchemy()

class User(db.Model, UserMixin):
    __tablename__ = "users"
    
    id = db.Column(db.Integer, primary_key = True)
    name = db.Column(db.String(200), nullable = False)
    email = db.Column(db.String(220), unique = True, nullable = False)
    phone_number = db.Column(db.String(20), nullable = True)
    password_hash = db.Column(db.String(255), nullable = True)
    google_id = db.Column(db.String(255), unique = True, nullable= True)
    
    created_at = db.Column(db.DateTime, default = datetime.utcnow)
    
    profile = db.relationship('UserProfile', backref = 'user', uselist = False)
    
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    
    profile = db.relationship('UserProfile', backref='user', uselist=False, cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'phone_number': self.phone_number
        }
        
class UserProfile(db.Model):
    __tablename__ = 'user_profiles'
    id = db.Column(db.Integer(), primary_key = True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable = False, unique = True)

    age_group = db.Column(db.String(20), nullable=True)
    height_range = db.Column(db.String(30), nullable=True)
    body_type = db.Column(db.String(30), nullable=True)
    skin_tone = db.Column(db.String(20), nullable=True)
    occasion = db.Column(db.String(30), nullable=True)
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'age_group' : self.age_group,
            'height_range' : self.height_range,
            'body_type' : self.body_type,
            'skin_tone' : self.skin_tone,
            'occasion' : self.occasion
        }       
        
        
class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    image_url = db.Column(db.String(300), nullable=True)

    best_for_body_types = db.Column(db.String(200), nullable=True)
    best_for_occasions = db.Column(db.String(200), nullable=True)

    fit_note = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'price': self.price,
            'category': self.category,
            'image_url': self.image_url,
            'fit_note': self.fit_note
        }


class Offer(db.Model):
    __tablename__ = 'offers'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    subtitle = db.Column(db.String(250), nullable=True)
    image_url = db.Column(db.String(300), nullable=False)
    link_url = db.Column(db.String(300), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)