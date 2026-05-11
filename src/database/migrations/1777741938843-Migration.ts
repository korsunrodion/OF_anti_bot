import { MigrationInterface, QueryRunner } from "typeorm";

export class Migration1777741938843 implements MigrationInterface {
    name = 'Migration1777741938843'

    public async up(queryRunner: QueryRunner): Promise<void> {
        await queryRunner.query(`ALTER TABLE "tracking_links_subscriber" ADD "is_internal_data" boolean NOT NULL DEFAULT false`);
    }

    public async down(queryRunner: QueryRunner): Promise<void> {
        await queryRunner.query(`ALTER TABLE "tracking_links_subscriber" DROP COLUMN "is_internal_data"`);
    }

}
