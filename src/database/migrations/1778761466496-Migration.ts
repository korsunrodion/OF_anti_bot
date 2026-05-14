import { MigrationInterface, QueryRunner } from 'typeorm';

export class Migration1778761466496 implements MigrationInterface {
  name = 'Migration1778761466496';

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`TRUNCATE TABLE "tracking_links_subscriber"`);
    await queryRunner.query(`TRUNCATE TABLE "tracking_links_input"`);
    await queryRunner.query(
      `ALTER TABLE "tracking_links_input" ADD "tracking_link_name" character varying NOT NULL`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" ADD "tracking_link_name" character varying NOT NULL`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_input" DROP COLUMN "tracking_link_id"`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_input" ADD "tracking_link_id" integer NOT NULL`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" DROP COLUMN "tracking_link_id"`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" ADD "tracking_link_id" integer NOT NULL`,
    );
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" DROP COLUMN "tracking_link_id"`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" ADD "tracking_link_id" character varying NOT NULL`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_input" DROP COLUMN "tracking_link_id"`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_input" ADD "tracking_link_id" character varying NOT NULL`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" DROP COLUMN "tracking_link_name"`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_input" DROP COLUMN "tracking_link_name"`,
    );
  }
}
