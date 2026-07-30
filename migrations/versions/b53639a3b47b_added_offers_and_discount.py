""" added offers and discount

Revision ID: b53639a3b47b
Revises: 320d8ff10b1e
Create Date: 2026-07-30 14:46:28.245572

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b53639a3b47b'
down_revision = '320d8ff10b1e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('discount_percent', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('offer_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_products_offer_id', 'offers', ['offer_id'], ['id'])

    # ### end Alembic commands ###


def downgrade():
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_constraint('fk_products_offer_id', type_='foreignkey')
        batch_op.drop_column('offer_id')
        batch_op.drop_column('discount_percent')

    # ### end Alembic commands ###
